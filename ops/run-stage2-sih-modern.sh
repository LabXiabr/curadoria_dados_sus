#!/usr/bin/env bash
set -Eeuo pipefail

MODE="dry-run"
MIN_FREE_GB="${MIN_FREE_GB:-500}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) MODE="execute"; shift ;;
    --min-free-gb) MIN_FREE_GB="$2"; shift 2 ;;
    -h|--help)
      echo "Uso: $0 [--execute] [--min-free-gb N]"
      echo "Etapa 2: SIH 200801_ staging -> Bronze -> CQ completude -> CQ TabNet."
      exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

STATE_ROOT="$LAKE_ROOT/state/stage2"
LOG_ROOT="$LAKE_ROOT/logs/stage2"
mkdir -p "$STATE_ROOT" "$LOG_ROOT"

RUN_ID="sih_modern_$(date '+%Y%m%d_%H%M%S')"
RUN="$STATE_ROOT/$RUN_ID"
LOG="$LOG_ROOT/$RUN_ID.log"
STATUS="$STATE_ROOT/current.status"
LATEST="$STATE_ROOT/LATEST"
LOCK="$STATE_ROOT/stage2_sih_modern.lock"
mkdir -p "$RUN"
printf '%s\n' "$RUN" > "$LATEST"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "ERRO: outra etapa 2 SIH ja esta em execucao: $LOCK" >&2
  exit 70
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
    echo "updated=$(date -Is)"
  } > "$tmp"
  mv -f "$tmp" "$STATUS"
}

on_error() {
  local rc=$?
  set +e
  write_status "FAILED" "${PHASE:-unknown}" "rc=$rc"
  echo "STAGE2_SIH_MODERN_FAILED rc=$rc phase=${PHASE:-unknown} run=$RUN log=$LOG"
  exit "$rc"
}
trap on_error ERR INT TERM

phase() {
  PHASE="$1"
  write_status "RUNNING" "$PHASE" "${2:-}"
  echo
  echo "===== STAGE2 PHASE $PHASE $(date -Is) ====="
}

echo "STAGE2_SIH_MODERN_START run=$RUN mode=$MODE commit=$(git -C "$REPO_ROOT" rev-parse HEAD)"
echo "lake=$LAKE_ROOT min_free_gb=$MIN_FREE_GB"
{
  echo "run_id=$RUN_ID"
  echo "started=$(date -Is)"
  echo "git_commit=$(git -C "$REPO_ROOT" rev-parse HEAD)"
  echo "mode=$MODE"
  echo "lake_root=$LAKE_ROOT"
} > "$RUN/run.env"

phase PRECHECK
for cmd in python3 psql duckdb dbview flock; do
  command -v "$cmd" >/dev/null || { echo "ERRO: comando ausente: $cmd" >&2; exit 71; }
done
python3 - <<'PY'
from html.parser import HTMLParser
from urllib.request import Request, urlopen
print("PYTHON_STDLIB_OK html.parser urllib")
PY

bash "$REPO_ROOT/ops/qc-stage1-suslabx.sh"

python3 "$REPO_ROOT/ops/qc-sih-tabnet-aih.py" \
  --preflight-only \
  --save-tabnet-html "$RUN/tabnet_preflight.html" \
  | tee "$RUN/tabnet_preflight.txt"

for svc in bureta pipeta; do
  psql "service=$svc" -X -At -P pager=off -c     "select current_database(),inet_server_addr(),inet_server_port();"     | sed "s/^/PSQL_OK $svc /"
done

avail_kb="$(df -Pk "$LAKE_ROOT" | awk 'NR==2{print $4}')"
min_kb=$((MIN_FREE_GB * 1024 * 1024))
if [[ ! "$avail_kb" =~ ^[0-9]+$ ]] || (( avail_kb < min_kb )); then
  echo "ERRO: espaco livre insuficiente em $LAKE_ROOT: avail_kb=$avail_kb min_kb=$min_kb" >&2
  exit 72
fi
df -h "$LAKE_ROOT"

phase STATUS_BEFORE
python3 "$REPO_ROOT/ops/status-migration.py"   --lake-root "$LAKE_ROOT" --system SIH --details   | tee "$RUN/status_before.txt"

phase SOURCE_STAGING_QC
python3 "$REPO_ROOT/ops/qc-sih-source-staging-live.py"   --lake-root "$LAKE_ROOT"   | tee "$RUN/qc_source_staging_live.txt"

phase PROMOTION_PLAN
python3 "$REPO_ROOT/ops/sih-promote-staging-bronze.py"   --lake-root "$LAKE_ROOT"   | tee "$RUN/promotion_plan.txt"

if [[ "$MODE" != "execute" ]]; then
  write_status "DRY_RUN_OK" "COMPLETE" "nenhuma alteracao executada"
  echo "STAGE2_SIH_MODERN_DRY_RUN_OK run=$RUN"
  exit 0
fi

phase PROMOTE_STAGING_BRONZE
python3 "$REPO_ROOT/ops/sih-promote-staging-bronze.py"   --lake-root "$LAKE_ROOT" --execute

phase DIRECT_ZERO_DBC
python3 "$REPO_ROOT/ops/sih-materialize-zero-dbc.py"   --lake-root "$LAKE_ROOT" --execute   | tee "$RUN/direct_zero_dbc.txt"

phase BRONZE_COMPLETENESS_QC
python3 "$REPO_ROOT/ops/qc-sih-bronze-modern.py"   --lake-root "$LAKE_ROOT"   | tee "$RUN/qc_bronze_modern.txt"

phase TABNET_AIH_QC
TABNET_REPORT="$RUN/qc_tabnet_aih_aprovadas.csv"
TABNET_HTML="$RUN/tabnet_qiuf.html"
python3 "$REPO_ROOT/ops/qc-sih-tabnet-aih.py"   --parquet-glob "$LAKE_ROOT/bronze/sih/200801_/rd/**/*.parquet"   --output "$TABNET_REPORT"   --save-tabnet-html "$TABNET_HTML"   | tee "$RUN/qc_tabnet.txt"

cat > "$LAKE_ROOT/state/sih/qc_tabnet_aih_current.ok" <<EOF
timestamp=$(date -Is)
series=200801_
report=$TABNET_REPORT
html=$TABNET_HTML
status=validated
EOF

phase STATUS_AFTER
python3 "$REPO_ROOT/ops/status-migration.py"   --lake-root "$LAKE_ROOT" --system SIH --details   | tee "$RUN/status_after.txt"

phase FINALIZE
MARKER="$STATE_ROOT/stage2_sih_modern_current.ok"
cat > "$MARKER.partial.$$" <<EOF
timestamp=$(date -Is)
run=$RUN
log=$LOG
series=200801_
bronze_qc=$LAKE_ROOT/state/sih/qc_bronze_modern_current.ok
tabnet_qc=$LAKE_ROOT/state/sih/qc_tabnet_aih_current.ok
status=validated
EOF
mv -f "$MARKER.partial.$$" "$MARKER"
write_status "OK" "COMPLETE" "stage2 validated"
echo "STAGE2_SIH_MODERN_OK run=$RUN marker=$MARKER log=$LOG"
