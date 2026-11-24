#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOBS="${JOBS:-4}"
PYTHON_BIN="${PYTHON_BIN:-$HOME/.venvs/suslabx/bin/python}"
SERIES="200801_"
STATE="$LAKE_ROOT/state/stage3_persist"
LOGS="$LAKE_ROOT/logs/stage3_persist"
mkdir -p "$STATE" "$LOGS"

RUN_ID="stage3_sia_persist_$(date '+%Y%m%d_%H%M%S')"
RUN="$STATE/$RUN_ID"
LOG="$LOGS/$RUN_ID.log"
STATUS="$STATE/current.status"
LOCK="$STATE/stage3_sia_persist.lock"
mkdir -p "$RUN"

GATE="$LAKE_ROOT/state/stage2_postqc/stage2_postqc_current.ok"
[[ -f "$GATE" ]] || {
  echo "ERRO: gate relacional da etapa 2 ausente: $GATE" >&2
  exit 80
}

exec 9>"$LOCK"
flock -n 9 || { echo "ERRO: persistencia SIA ja em execucao" >&2; exit 81; }
exec > >(tee -a "$LOG") 2>&1

write_status(){
  local st="$1" phase="$2" detail="${3:-}"
  local tmp="$STATUS.partial.$$"
  {
    echo "status=$st"
    echo "phase=$phase"
    echo "detail=$detail"
    echo "run=$RUN"
    echo "log=$LOG"
    echo "pid=$$"
    echo "series=$SERIES"
    echo "jobs=$JOBS"
    echo "git_commit=$(git -C "$ROOT" rev-parse HEAD)"
    echo "updated=$(date -Is)"
  } > "$tmp"
  mv -f "$tmp" "$STATUS"
}
onerr(){
  local rc=$?
  set +e
  write_status FAILED "${PHASE:-unknown}" "rc=$rc"
  echo "STAGE3_SIA_PERSIST_FAILED rc=$rc phase=${PHASE:-unknown} log=$LOG"
  exit "$rc"
}
trap onerr ERR INT TERM

PHASE=PRECHECK
write_status RUNNING "$PHASE"
for cmd in psql flock; do
  command -v "$cmd" >/dev/null || { echo "ERRO: comando ausente $cmd" >&2; exit 82; }
done
for svc in bureta pipeta; do
  psql "service=$svc" -X -At -P pager=off -c     "select current_database(),inet_server_addr(),inet_server_port();"     | sed "s/^/PSQL_OK $svc /"
done
df -h "$LAKE_ROOT"

PHASE=PLAN
write_status RUNNING "$PHASE"
"$PYTHON_BIN" "$ROOT/ops/sia-psql-snapshot-overnight_arrow.py"   --lake-root "$LAKE_ROOT" --series "$SERIES" --jobs "$JOBS"   --plan-only --run-id "${RUN_ID}_plan"   | tee "$RUN/plan.txt"

PHASE=PERSIST_SQL_PRESENT
write_status RUNNING "$PHASE"
SIA_RUN_ID="sia_${RUN_ID}"
"$PYTHON_BIN" "$ROOT/ops/sia-psql-snapshot-overnight_arrow.py"   --lake-root "$LAKE_ROOT" --series "$SERIES" --jobs "$JOBS"   --run-id "$SIA_RUN_ID"   | tee "$RUN/persist.txt"

LATEST_SIA="$LAKE_ROOT/state/overnight/LATEST_SIA"
[[ -f "$LATEST_SIA" ]] || { echo "ERRO: LATEST_SIA ausente" >&2; exit 83; }
SIA_RUN="$(cat "$LATEST_SIA")"
RESULTS="$SIA_RUN/sia_parquet_results.tsv"
MAINLOG="$SIA_RUN/main.log"
[[ -f "$RESULTS" && -f "$MAINLOG" ]] || { echo "ERRO: run SIA incompleto: $SIA_RUN" >&2; exit 84; }
grep -qx 'OVERNIGHT_DONE' "$MAINLOG" || { echo "ERRO: SIA sem OVERNIGHT_DONE" >&2; exit 85; }

PHASE=SUMMARY
write_status RUNNING "$PHASE"
"$PYTHON_BIN" "$ROOT/ops/status-migration.py"   --lake-root "$LAKE_ROOT" --system SIA --details   | tee "$RUN/status_after.txt"

files="$(awk 'END{print NR-1}' "$RESULTS")"
ok="$(awk -F '\t' 'NR>1 && ($9=="OK" || $9=="SKIP_OK"){n++} END{print n+0}' "$RESULTS")"
bad="$(awk -F '\t' 'NR>1 && !($9=="OK" || $9=="SKIP_OK"){n++} END{print n+0}' "$RESULTS")"
(( bad == 0 )) || { echo "ERRO: resultados SIA com falhas: $bad" >&2; exit 86; }

MARKER="$STATE/stage3_sia_sql_present_current.ok"
cat > "$MARKER.partial.$$" <<EOF
timestamp=$(date -Is)
run=$RUN
log=$LOG
source_run=$SIA_RUN
series=$SERIES
jobs=$JOBS
files=$files
ok=$ok
bad=$bad
scope=sql_present_only
missing_sql=not_yet_materialized
status=persisted
EOF
mv -f "$MARKER.partial.$$" "$MARKER"

write_status OK COMPLETE "files=$files ok=$ok scope=sql_present_only"
echo "STAGE3_SIA_PERSIST_OK files=$files ok=$ok marker=$MARKER"
