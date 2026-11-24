#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATUS="$LAKE_ROOT/state/nightly/current.status"

echo "=== NIGHTLY STATUS $(date -Is) ==="
if [[ -f "$STATUS" ]]; then
  cat "$STATUS"
else
  echo "status=NOT_STARTED"
fi

echo
echo "=== PROCESS ==="
pgrep -af 'run-nightly-stage2-stage3|run-stage2-sih-modern|run-stage3-sia-modern|sih-promote-staging-bronze|sia-psql-snapshot-overnight|sia-build-pa-enriched' || true

echo
echo "=== STAGE2 ==="
bash "$ROOT/ops/status-stage2-sih-modern.sh" | sed -n '1,28p' || true

echo
echo "=== STAGE3 ==="
bash "$ROOT/ops/status-stage3-sia-modern.sh" | sed -n '1,28p' || true

echo
echo "=== DISK ==="
df -h "$LAKE_ROOT"
