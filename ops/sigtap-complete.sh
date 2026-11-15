#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== ETAPA 1/3: BRONZE SIGTAP COMPLETA + QC POR COMPETENCIA ==="
"$ROOT/ops/sigtap-backfill-bronze.sh" "$@"

echo
echo "=== ETAPA 2/3: QC GLOBAL BRONZE (FTP = RAW = BRONZE = MARKERS) ==="
"$ROOT/ops/qc-sigtap-global.sh"

echo
echo "=== ETAPA 3/3: SILVER TEMPORAL LOSSLESS ==="
python3 "$ROOT/etl/parquet_duckdb/sigtap/build_silver.py"

echo
echo "SIGTAP_COMPLETE_OK"
