#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
JOBS_STAGE3="${JOBS_STAGE3:-2}"
WITH_STAGE3=0
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-stage3) WITH_STAGE3=1; shift ;;
    -h|--help)
      echo "Uso: $0 [--with-stage3]"
      echo "Padrao seguro: executa apenas etapa 2. Etapa 3 exige opt-in explicito."
      exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

STATE="$LAKE_ROOT/state/nightly"
LOGS="$LAKE_ROOT/logs/nightly"
mkdir -p "$STATE" "$LOGS"

RUN_ID="nightly_$(date '+%Y%m%d_%H%M%S')"
LOG="$LOGS/$RUN_ID.log"
STATUS="$STATE/current.status"
LOCK="$STATE/nightly_stage2_stage3.lock"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "ERRO: outro encadeamento noturno ja esta ativo: $LOCK" >&2
  exit 90
fi

exec > >(tee -a "$LOG") 2>&1

write_status() {
  local st="$1" phase="$2" detail="${3:-}"
  local tmp="$STATUS.partial.$$"
  {
    echo "status=$st"
    echo "phase=$phase"
    echo "detail=$detail"
    echo "run_id=$RUN_ID"
    echo "log=$LOG"
    echo "pid=$$"
    echo "git_commit=$(git -C "$ROOT" rev-parse HEAD)"
    echo "updated=$(date -Is)"
  } > "$tmp"
  mv -f "$tmp" "$STATUS"
}

fail() {
  local rc=$?
  set +e
  write_status "FAILED" "${PHASE:-unknown}" "rc=$rc"
  echo "SUSLABX_NIGHTLY_FAILED rc=$rc phase=${PHASE:-unknown} log=$LOG"
  exit "$rc"
}
trap fail ERR INT TERM

PHASE="PRECHECK"
write_status "RUNNING" "$PHASE"
echo "SUSLABX_NIGHTLY_START timestamp=$(date -Is) commit=$(git -C "$ROOT" rev-parse HEAD)"

bash "$ROOT/ops/qc-stage1-suslabx.sh"

PHASE="STAGE2_SIH_MODERN"
write_status "RUNNING" "$PHASE"
bash "$ROOT/ops/run-stage2-sih-modern.sh" --execute

stage2_marker="$LAKE_ROOT/state/stage2/stage2_sih_modern_current.ok"
[[ -f "$stage2_marker" ]] || {
  echo "ERRO: etapa 2 retornou sucesso sem marker: $stage2_marker" >&2
  exit 91
}

if (( WITH_STAGE3 == 1 )); then
  PHASE="STAGE3_SIA_MODERN"
  write_status "RUNNING" "$PHASE"
  bash "$ROOT/ops/run-stage3-sia-modern.sh" --execute --jobs "$JOBS_STAGE3"

  stage3_marker="$LAKE_ROOT/state/stage3/stage3_sia_modern_pa_current.ok"
  [[ -f "$stage3_marker" ]] || {
    echo "ERRO: etapa 3 retornou sucesso sem marker: $stage3_marker" >&2
    exit 92
  }
else
  echo "STAGE3_SKIPPED: opt-in --with-stage3 nao informado"
fi

PHASE="REPORT"
write_status "RUNNING" "$PHASE"
bash "$ROOT/ops/report-overnight-suslabx.sh"   | tee "$STATE/$RUN_ID.report.txt"

PHASE="COMPLETE"
if (( WITH_STAGE3 == 1 )); then
  detail="stage2+stage3 validated"
else
  detail="stage2 validated; stage3 skipped"
fi
write_status "OK" "$PHASE" "$detail"
echo "SUSLABX_NIGHTLY_OK with_stage3=$WITH_STAGE3 report=$STATE/$RUN_ID.report.txt log=$LOG"
