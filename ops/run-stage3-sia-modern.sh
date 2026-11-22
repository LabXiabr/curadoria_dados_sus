#!/usr/bin/env bash
set -Eeuo pipefail

MODE="dry-run"
WAIT_STAGE2=0
JOBS="${JOBS:-2}"
POLL_SECONDS="${POLL_SECONDS:-60}"
MIN_FREE_GB="${MIN_FREE_GB:-500}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERIES="200801_"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) MODE="execute"; shift ;;
    --wait-stage2) WAIT_STAGE2=1; shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --poll-seconds) POLL_SECONDS="$2"; shift 2 ;;
    --min-free-gb) MIN_FREE_GB="$2"; shift 2 ;;
    -h|--help)
      echo "Uso: $0 [--execute] [--wait-stage2] [--jobs N]"
      echo "Etapa 3: snapshot SIA 200801_ -> CQ -> Silver PA enriquecida CNSPCN."
      exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

[[ "$JOBS" =~ ^[0-9]+$ ]] && (( JOBS >= 1 )) || { echo "ERRO: --jobs invalido" >&2; exit 2; }

STAGE2_MARKER="$LAKE_ROOT/state/stage2/stage2_sih_modern_current.ok"
STAGE2_STATUS="$LAKE_ROOT/state/stage2/current.status"

wait_stage2() {
  if [[ -f "$STAGE2_MARKER" ]]; then
    return 0
  fi
  if (( WAIT_STAGE2 == 0 )); then
    echo "ERRO: gate da etapa 2 ausente: $STAGE2_MARKER" >&2
    exit 80
  fi
  echo "STAGE3_WAITING_FOR_STAGE2 marker=$STAGE2_MARKER poll=$POLL_SECONDS"
  while [[ ! -f "$STAGE2_MARKER" ]]; do
    if [[ -f "$STAGE2_STATUS" ]]; then
      st="$(awk -F= '$1=="status"{print $2;exit}' "$STAGE2_STATUS")"
      ph="$(awk -F= '$1=="phase"{print $2;exit}' "$STAGE2_STATUS")"
      echo "WAIT_STAGE2 $(date -Is) status=${st:-unknown} phase=${ph:-unknown}"
      if [[ "$st" == "FAILED" ]]; then
        echo "ERRO: etapa 2 falhou; etapa 3 nao sera iniciada" >&2
        exit 81
      fi
    else
      echo "WAIT_STAGE2 $(date -Is) status=unknown"
    fi
    sleep "$POLL_SECONDS"
  done
  echo "STAGE2_GATE_OK $(date -Is)"
}

wait_stage2

STATE_ROOT="$LAKE_ROOT/state/stage3"
LOG_ROOT="$LAKE_ROOT/logs/stage3"
mkdir -p "$STATE_ROOT" "$LOG_ROOT"
RUN_ID="sia_modern_$(date '+%Y%m%d_%H%M%S')"
RUN="$STATE_ROOT/$RUN_ID"
LOG="$LOG_ROOT/$RUN_ID.log"
STATUS="$STATE_ROOT/current.status"
LATEST="$STATE_ROOT/LATEST"
LOCK="$STATE_ROOT/stage3_sia_modern.lock"
mkdir -p "$RUN"
printf '%s\n' "$RUN" > "$LATEST"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "ERRO: outra etapa 3 SIA ja esta em execucao" >&2
  exit 82
fi

exec > >(tee -a "$LOG") 2>&1

write_status() {
  local state="$1" phase="$2" detail="${3:-}"
  local tmp="$STATUS.partial.$$"
  {
    echo "status=$state"
    echo "phase=$phase"
    echo "detail=$detail"
    echo "run=$RUN"
    echo "log=$LOG"
    echo "pid=$$"
    echo "mode=$MODE"
    echo "series=$SERIES"
    echo "jobs=$JOBS"
    echo "updated=$(date -Is)"
  } > "$tmp"
  mv -f "$tmp" "$STATUS"
}

on_error() {
  local rc=$?
  set +e
  write_status "FAILED" "${PHASE:-unknown}" "rc=$rc"
  echo "STAGE3_SIA_MODERN_FAILED rc=$rc phase=${PHASE:-unknown} run=$RUN log=$LOG"
  exit "$rc"
}
trap on_error ERR INT TERM

phase() {
  PHASE="$1"
  write_status "RUNNING" "$PHASE" "${2:-}"
  echo
  echo "===== STAGE3 PHASE $PHASE $(date -Is) ====="
}

echo "STAGE3_SIA_MODERN_START run=$RUN mode=$MODE series=$SERIES jobs=$JOBS commit=$(git -C "$REPO_ROOT" rev-parse HEAD)"
{
  echo "run_id=$RUN_ID"
  echo "started=$(date -Is)"
  echo "git_commit=$(git -C "$REPO_ROOT" rev-parse HEAD)"
  echo "mode=$MODE"
  echo "series=$SERIES"
  echo "jobs=$JOBS"
} > "$RUN/run.env"

phase PRECHECK
bash "$REPO_ROOT/ops/qc-stage1-suslabx.sh"
[[ -f "$STAGE2_MARKER" ]] || { echo "ERRO: etapa 2 perdeu marker durante precheck" >&2; exit 83; }
for cmd in python3 psql duckdb flock; do
  command -v "$cmd" >/dev/null || { echo "ERRO: comando ausente: $cmd" >&2; exit 84; }
done
for svc in bureta pipeta; do
  psql "service=$svc" -X -At -P pager=off -c     "select current_database(),inet_server_addr(),inet_server_port();"     | sed "s/^/PSQL_OK $svc /"
done
avail_kb="$(df -Pk "$LAKE_ROOT" | awk 'NR==2{print $4}')"
min_kb=$((MIN_FREE_GB * 1024 * 1024))
if [[ ! "$avail_kb" =~ ^[0-9]+$ ]] || (( avail_kb < min_kb )); then
  echo "ERRO: espaco livre insuficiente: avail_kb=$avail_kb min_kb=$min_kb" >&2
  exit 85
fi
df -h "$LAKE_ROOT"

phase STATUS_BEFORE
python3 "$REPO_ROOT/ops/status-migration.py"   --lake-root "$LAKE_ROOT" --system SIA --details   | tee "$RUN/status_before.txt"

phase SNAPSHOT_PREFLIGHT
python3 "$REPO_ROOT/ops/sia-psql-snapshot-overnight.py"   --lake-root "$LAKE_ROOT" --series "$SERIES" --jobs 1 --limit 2   --run-id "$RUN_ID"_preflight   | tee "$RUN/snapshot_preflight.txt"

if [[ "$MODE" != "execute" ]]; then
  write_status "DRY_RUN_OK" "COMPLETE" "preflight limitado executado"
  echo "STAGE3_SIA_MODERN_DRY_RUN_OK run=$RUN"
  exit 0
fi

phase SNAPSHOT_FULL
SIA_RUN_ID="sia_$RUN_ID"
python3 "$REPO_ROOT/ops/sia-psql-snapshot-overnight.py"   --lake-root "$LAKE_ROOT" --series "$SERIES" --jobs "$JOBS"   --run-id "$SIA_RUN_ID"

phase SOURCE_STAGING_QC
python3 "$REPO_ROOT/ops/qc-sia-source-staging-live.py"   --lake-root "$LAKE_ROOT" --series "$SERIES"   | tee "$RUN/qc_source_staging_live.txt"

phase PA_ENRICH_PLAN
python3 "$REPO_ROOT/ops/sia-build-pa-enriched.py"   --lake-root "$LAKE_ROOT" --source staging --series "$SERIES" --limit 3   | tee "$RUN/pa_enrich_plan.txt"

phase PA_ENRICH_FULL
python3 "$REPO_ROOT/ops/sia-build-pa-enriched.py"   --lake-root "$LAKE_ROOT" --source staging --series "$SERIES" --execute

PA_REPORT="$LAKE_ROOT/state/sia/pa_cnspcn_enrichment.tsv"
python3 - "$PA_REPORT" <<'PY'
import csv,sys
p=sys.argv[1]
with open(p,encoding="utf-8",newline="") as f:
    rows=list(csv.DictReader(f,delimiter="\t"))
bad=[r for r in rows if r.get("status")!="ok"]
if not rows:
    raise SystemExit("ERRO: relatorio PA enriquecida vazio")
if bad:
    print("ERRO: PA enriquecida possui status nao-ok:",len(bad))
    for r in bad[:20]:
        print(r)
    raise SystemExit(20)
print(f"SIA_PA_ENRICH_REPORT_OK files={len(rows)}")
PY

phase STATUS_AFTER
python3 "$REPO_ROOT/ops/status-migration.py"   --lake-root "$LAKE_ROOT" --system SIA --details   | tee "$RUN/status_after.txt"

phase FINALIZE
MARKER="$STATE_ROOT/stage3_sia_modern_pa_current.ok"
cat > "$MARKER.partial.$$" <<EOF
timestamp=$(date -Is)
run=$RUN
log=$LOG
series=$SERIES
source_staging_qc=$LAKE_ROOT/state/sia/qc_source_staging_live_current.ok
pa_enrichment_report=$PA_REPORT
status=validated
EOF
mv -f "$MARKER.partial.$$" "$MARKER"
write_status "OK" "COMPLETE" "stage3 validated"
echo "STAGE3_SIA_MODERN_PA_OK run=$RUN marker=$MARKER log=$LOG"
