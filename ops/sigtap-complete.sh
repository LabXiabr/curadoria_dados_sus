#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== ETAPA 1/2: BRONZE SIGTAP COMPLETA + QC ==="
"$ROOT/ops/sigtap-backfill-bronze.sh" "$@"

echo
echo "=== ETAPA 2/2: SILVER TEMPORAL LOSSLESS ==="
python3 "$ROOT/etl/parquet_duckdb/sigtap/build_silver.py"

echo
echo "SIGTAP_COMPLETE_OK"
