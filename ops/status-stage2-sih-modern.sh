#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
STATE_ROOT="$LAKE_ROOT/state/stage2"
STATUS="$STATE_ROOT/current.status"

echo "=== STAGE2 STATUS $(date -Is) ==="
if [[ -f "$STATUS" ]]; then
  cat "$STATUS"
else
  echo "status=NOT_STARTED"
fi

echo
echo "=== PROCESS ==="
pgrep -af 'run-stage2-sih-modern|sih-promote-staging-bronze|qc-sih|sih-materialize-zero' || true

echo
echo "=== BRONZE FILES ==="
if [[ -d "$LAKE_ROOT/bronze/sih/200801_" ]]; then
  n="$(find "$LAKE_ROOT/bronze/sih/200801_" -type f -name '*.dbc.parquet' 2>/dev/null | wc -l)"
  echo "bronze_dbc_files=$n"
else
  echo "bronze_dbc_files=0"
fi

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
  tail -40 "$log"
else
  echo "log indisponivel"
fi

echo
echo "=== FINAL MARKER ==="
marker="$STATE_ROOT/stage2_sih_modern_current.ok"
if [[ -f "$marker" ]]; then
  cat "$marker"
else
  echo "stage2_marker=absent"
fi
