#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
JOBS_STAGE3="${JOBS_STAGE3:-2}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

PHASE="STAGE3_SIA_MODERN"
write_status "RUNNING" "$PHASE"
bash "$ROOT/ops/run-stage3-sia-modern.sh" --execute --jobs "$JOBS_STAGE3"

stage3_marker="$LAKE_ROOT/state/stage3/stage3_sia_modern_pa_current.ok"
[[ -f "$stage3_marker" ]] || {
  echo "ERRO: etapa 3 retornou sucesso sem marker: $stage3_marker" >&2
  exit 92
}

PHASE="REPORT"
write_status "RUNNING" "$PHASE"
bash "$ROOT/ops/report-overnight-suslabx.sh"   | tee "$STATE/$RUN_ID.report.txt"

PHASE="COMPLETE"
write_status "OK" "$PHASE" "stage2+stage3 validated"
echo "SUSLABX_NIGHTLY_OK report=$STATE/$RUN_ID.report.txt log=$LOG"
