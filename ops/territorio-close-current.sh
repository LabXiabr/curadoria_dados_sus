#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== 1/3 RECONSTRUIR CONTEXTO MUNICIPAL ==="
python3 "$ROOT/etl/parquet_duckdb/reference/build_municipio_contexto.py"

echo
echo "=== 2/3 QC TERRITORIO X REGIONALIZACAO PORTAL ==="
python3 "$ROOT/ops/qc-territorio-regionalizacao.py"

echo
echo "=== 3/3 GATE TERRITORIAL CORRENTE ==="
python3 "$ROOT/ops/qc-territorio-current.py"

echo
echo "TERRITORIO_CLOSE_CURRENT_OK"
