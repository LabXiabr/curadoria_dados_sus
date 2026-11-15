#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/ops/cnes-acquire-reference.sh" --artifact cep
python3 "$ROOT/etl/parquet_duckdb/cnes/build_cep.py"
