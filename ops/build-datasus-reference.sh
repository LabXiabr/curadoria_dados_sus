#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 -m py_compile \
  "$ROOT/ops/inspect-datasus-auxiliary.py" \
  "$ROOT/etl/parquet_duckdb/reference/build_datasus_auxiliary.py" \
  "$ROOT/ops/qc-datasus-reference.py"

"$ROOT/ops/inspect-datasus-auxiliary.py"
python3 "$ROOT/etl/parquet_duckdb/reference/build_datasus_auxiliary.py" "$@"
python3 "$ROOT/ops/qc-datasus-reference.py"

echo "DATASUS_REFERENCE_COMPLETE_OK"
