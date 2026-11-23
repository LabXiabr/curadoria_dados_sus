#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$LAKE_ROOT/state/stage2_postqc"
LOGS="$LAKE_ROOT/logs/stage2_postqc"
mkdir -p "$STATE" "$LOGS"

RUN_ID="stage2_postqc_$(date '+%Y%m%d_%H%M%S')"
RUN="$STATE/$RUN_ID"
LOG="$LOGS/$RUN_ID.log"
STATUS="$STATE/current.status"
LOCK="$STATE/stage2_postqc.lock"
mkdir -p "$RUN"

exec 9>"$LOCK"
flock -n 9 || { echo "ERRO: stage2 post-QC ja em execucao" >&2; exit 90; }
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
    echo "git_commit=$(git -C "$ROOT" rev-parse HEAD)"
    echo "updated=$(date -Is)"
  } > "$tmp"
  mv -f "$tmp" "$STATUS"
}
onerr(){
  local rc=$?
  set +e
  write_status FAILED "${PHASE:-unknown}" "rc=$rc"
  echo "STAGE2_POSTQC_FAILED rc=$rc phase=${PHASE:-unknown} log=$LOG"
  exit "$rc"
}
trap onerr ERR INT TERM

PHASE=BRONZE_COMPLETENESS
write_status RUNNING "$PHASE"
python3 "$ROOT/ops/qc-sih-bronze-modern.py" --lake-root "$LAKE_ROOT"   | tee "$RUN/bronze_completeness.txt"

PHASE=TABNET_AIH
write_status RUNNING "$PHASE"
# O CQ TabNet e diagnostico pos-persistencia. Colocar a pipeline dentro de IF
# impede que trap ERR encerre o orquestrador quando o comparador retorna 10.
if python3 "$ROOT/ops/qc-sih-tabnet-aih.py" \
  --parquet-glob "$LAKE_ROOT/bronze/sih/200801_/rd/**/*.parquet" \
  --output "$RUN/qc_tabnet_aih_aprovadas.csv" \
  --save-tabnet-html "$RUN/tabnet_qiuf.html" \
  | tee "$RUN/qc_tabnet.txt"; then
  TABNET_RC=0
else
  TABNET_RC=${PIPESTATUS[0]}
fi
if (( TABNET_RC == 0 )); then
  TABNET_STATUS="validated"
else
  TABNET_STATUS="warning_rc_$TABNET_RC"
  echo "WARN: CQ TabNet divergente; persistencia posterior nao sera bloqueada."
fi

PHASE=DIMENSION_RELATIONS_HEAVY
write_status RUNNING "$PHASE" "tabnet=$TABNET_STATUS"
python3 "$ROOT/ops/qc-sih-dimensions-heavy.py"   --lake-root "$LAKE_ROOT"   | tee "$RUN/qc_dimensions_heavy.txt"

PHASE=FINALIZE
write_status RUNNING "$PHASE" "tabnet=$TABNET_STATUS"
MARKER="$STATE/stage2_postqc_current.ok"
cat > "$MARKER.partial.$$" <<EOF
timestamp=$(date -Is)
run=$RUN
log=$LOG
bronze_qc=$LAKE_ROOT/state/sih/qc_bronze_modern_current.ok
dimension_qc=$LAKE_ROOT/state/sih/qc_dimensions_current.ok
tabnet_status=$TABNET_STATUS
tabnet_report=$RUN/qc_tabnet_aih_aprovadas.csv
status=validated_for_persistence
EOF
mv -f "$MARKER.partial.$$" "$MARKER"

if [[ "$TABNET_STATUS" == "validated" ]]; then
  SEM="$STATE/stage2_semantic_current.ok"
  cat > "$SEM.partial.$$" <<EOF
timestamp=$(date -Is)
run=$RUN
tabnet=validated
dimensions=validated
bronze=validated
status=semantic_validated
EOF
  mv -f "$SEM.partial.$$" "$SEM"
  echo "STAGE2_SEMANTIC_QC_OK marker=$SEM"
else
  rm -f "$STATE/stage2_semantic_current.ok"
  echo "STAGE2_SEMANTIC_QC_WARNING tabnet=$TABNET_STATUS"
fi

write_status OK COMPLETE "tabnet=$TABNET_STATUS dimensions=validated"
echo "STAGE2_POSTQC_OK marker=$MARKER tabnet=$TABNET_STATUS"
