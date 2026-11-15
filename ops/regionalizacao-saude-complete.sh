#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/ops/regionalizacao-saude-acquire.sh"
python3 "$ROOT/etl/parquet_duckdb/reference/build_regionalizacao_saude.py"
