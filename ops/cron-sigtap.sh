#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
STATE="$LAKE_ROOT/state/sigtap"
LOGROOT="$LAKE_ROOT/logs/sigtap"
mkdir -p "$STATE" "$LOGROOT"

exec 9>"$STATE/cron.lock"
if ! flock -n 9; then
    echo "SIGTAP_CRON_SKIP lock_held"
    exit 0
fi

ts="$(date +%Y%m%d_%H%M%S)"
log="$LOGROOT/cron_refresh_${ts}.log"
exec > >(tee -a "$log") 2>&1

echo "SIGTAP_CRON_START $(date -Is)"

"$ROOT/ops/sigtap-backfill-bronze.sh"
"$ROOT/ops/qc-sigtap-global.sh"

silver_marker="$STATE/silver_complete.ok"
need_silver=0

if [[ ! -f "$silver_marker" ]]; then
    need_silver=1
else
    while IFS= read -r marker; do
        if [[ "$marker" -nt "$silver_marker" ]]; then
            need_silver=1
            break
        fi
    done < <(find "$STATE" -maxdepth 1 -type f -name 'qc_raw_bronze_??????.ok' -print | sort)
fi

if (( need_silver == 1 )); then
    echo "SIGTAP_SILVER_REBUILD reason=bronze_changed_or_missing"
    python3 "$ROOT/etl/parquet_duckdb/sigtap/build_silver.py"
else
    echo "SIGTAP_SILVER_UP_TO_DATE"
fi

echo "SIGTAP_CRON_OK $(date -Is) log=$log"
