#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/ops/ibge-localidades-acquire.sh"
python3 "$ROOT/etl/parquet_duckdb/reference/build_ibge_localidades.py"
python3 "$ROOT/etl/parquet_duckdb/reference/build_ra_df.py"
echo "IBGE_LOCALIDADES_COMPLETE_OK"
