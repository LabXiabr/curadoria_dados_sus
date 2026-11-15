#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
STATE="$LAKE_ROOT/state/dissemin"
LOGROOT="$LAKE_ROOT/logs/dissemin"
mkdir -p "$STATE" "$LOGROOT"

exec 9>"$STATE/ftp_inventory_cron.lock"
if ! flock -n 9; then
    echo "DISSEMIN_INVENTORY_CRON_SKIP lock_held"
    exit 0
fi

ts="$(date +%Y%m%d_%H%M%S)"
log="$LOGROOT/cron_ftp_inventory_${ts}.log"
exec > >(tee -a "$log") 2>&1

echo "DISSEMIN_INVENTORY_CRON_START $(date -Is)"
cd "$ROOT"

python3 "$ROOT/ops/inventory-dissemin-ftp.py"

if [[ -f "$STATE/dbc_legacy_dedupe_complete.ok" ]]; then
    python3 "$ROOT/ops/reconcile-dbc-legacy.py"
else
    echo "DISSEMIN_RECONCILE_SKIP dedupe_marker_absent"
fi

echo "DISSEMIN_INVENTORY_CRON_OK $(date -Is) log=$log"
