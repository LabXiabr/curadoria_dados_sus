#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
STATE_ROOT="$LAKE_ROOT/state/stage3"
STATUS="$STATE_ROOT/current.status"

echo "=== STAGE3 STATUS $(date -Is) ==="
if [[ -f "$STATUS" ]]; then
  cat "$STATUS"
else
  echo "status=NOT_STARTED"
fi

echo
echo "=== PROCESS ==="
pgrep -af 'run-stage3-sia-modern|sia-psql-snapshot-overnight|sia-build-pa-enriched|qc-sia-source-staging-live' || true

echo
echo "=== STAGING SIA 200801_ ==="
if [[ -d "$LAKE_ROOT/staging/psql_snapshot/sia/200801_" ]]; then
  n="$(find "$LAKE_ROOT/staging/psql_snapshot/sia/200801_" -type f -name '*.parquet' 2>/dev/null | wc -l)"
  echo "staging_parquet_files=$n"
else
  echo "staging_parquet_files=0"
fi

echo
echo "=== SILVER PA ENRICHED 200801_ ==="
if [[ -d "$LAKE_ROOT/silver/sia/200801_/pa_enriched" ]]; then
  n="$(find "$LAKE_ROOT/silver/sia/200801_/pa_enriched" -type f -name '*.parquet' 2>/dev/null | wc -l)"
  echo "pa_enriched_files=$n"
else
  echo "pa_enriched_files=0"
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
marker="$STATE_ROOT/stage3_sia_modern_pa_current.ok"
if [[ -f "$marker" ]]; then
  cat "$marker"
else
  echo "stage3_marker=absent"
fi
