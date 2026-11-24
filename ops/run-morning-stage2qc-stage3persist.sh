#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$LAKE_ROOT/state/morning_stage2_stage3"
LOGS="$LAKE_ROOT/logs/morning_stage2_stage3"
mkdir -p "$STATE" "$LOGS"

RUN_ID="morning_$(date '+%Y%m%d_%H%M%S')"
LOG="$LOGS/$RUN_ID.log"
STATUS="$STATE/current.status"
LOCK="$STATE/morning.lock"

exec 9>"$LOCK"
flock -n 9 || { echo "ERRO: rodada matinal ja ativa" >&2; exit 90; }
exec > >(tee -a "$LOG") 2>&1

write_status(){
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
onerr(){
  local rc=$?
  set +e
  write_status FAILED "${PHASE:-unknown}" "rc=$rc"
  echo "MORNING_STAGE2_STAGE3_FAILED rc=$rc phase=${PHASE:-unknown} log=$LOG"
  exit "$rc"
}
trap onerr ERR INT TERM

echo "MORNING_STAGE2_STAGE3_START $(date -Is) commit=$(git -C "$ROOT" rev-parse HEAD)"

PHASE=STAGE2_POSTQC
write_status RUNNING "$PHASE"
bash "$ROOT/ops/run-stage2-postqc.sh"

PHASE=STAGE3_SIA_PERSIST
write_status RUNNING "$PHASE"
JOBS="${JOBS:-4}" bash "$ROOT/ops/run-stage3-sia-persist.sh"

PHASE=COMPLETE
write_status OK "$PHASE" "stage2_postqc_done; stage3_sia_sql_present_persisted"
echo "MORNING_STAGE2_STAGE3_OK log=$LOG"
