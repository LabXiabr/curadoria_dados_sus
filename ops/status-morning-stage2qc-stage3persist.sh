#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATUS="$LAKE_ROOT/state/morning_stage2_stage3/current.status"

echo "=== MORNING STATUS $(date -Is) ==="
if [[ -f "$STATUS" ]]; then
  cat "$STATUS"
else
  echo "status=NOT_STARTED"
fi

echo
echo "=== PROCESS ==="
pgrep -af 'run-morning-stage2qc-stage3persist|run-stage2-postqc|qc-sih-dimensions-heavy|run-stage3-sia-persist|sia-psql-snapshot-overnight' || true

echo
echo "=== STAGE2 POST-QC ==="
if [[ -f "$LAKE_ROOT/state/stage2_postqc/current.status" ]]; then
  cat "$LAKE_ROOT/state/stage2_postqc/current.status"
else
  echo "status=NOT_STARTED"
fi

echo
echo "=== STAGE3 PERSIST ==="
if [[ -f "$LAKE_ROOT/state/stage3_persist/current.status" ]]; then
  cat "$LAKE_ROOT/state/stage3_persist/current.status"
else
  echo "status=NOT_STARTED"
fi

echo
echo "=== SIA STAGING FILES ==="
n="$(find "$LAKE_ROOT/staging/psql_snapshot/sia/200801_" -type f -name '*.parquet' 2>/dev/null | wc -l)"
echo "sia_200801_parquet_files=$n"

echo
echo "=== DISK ==="
df -h "$LAKE_ROOT"

echo
echo "=== LOG TAIL ==="
log=""
if [[ -f "$STATUS" ]]; then
  log="$(awk -F= '$1=="log"{sub(/^log=/,"");print;exit}' "$STATUS")"
fi
if [[ -n "$log" && -f "$log" ]]; then
  tail -50 "$log"
else
  echo "log indisponivel"
fi
