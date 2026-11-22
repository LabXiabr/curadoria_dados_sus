#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMP="${1:-202610}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
STATE="$LAKE_ROOT/state/cnes"
mkdir -p "$STATE"

"$ROOT/ops/cnes-preflight.sh"

# Falhar cedo em qualquer erro de sintaxe Python.
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/curadoria_dados_sus_pycache}"
python3 -m py_compile \
  "$ROOT/etl/parquet_duckdb/reference/build_ibge_localidades.py" \
  "$ROOT/etl/parquet_duckdb/reference/build_ra_df.py" \
  "$ROOT/etl/parquet_duckdb/reference/build_municipio_contexto.py" \
  "$ROOT/etl/parquet_duckdb/reference/build_territorio_conformado.py" \
  "$ROOT/etl/parquet_duckdb/cnes/build_df_ra_crosswalk.py" \
  "$ROOT/etl/parquet_duckdb/cnes/build_silver_current.py" \
  "$ROOT/ops/build-cnes-duckdb-views.py" \
  "$ROOT/ops/qc-cnes-drill-territorial.py" \
  "$ROOT/ops/cnes-classify-tables.py" \
  "$ROOT/ops/qc-cnes-global.py" \
  "$ROOT/ops/cnes-promote-silver-snapshot.py"
echo "CNES_PYTHON_SYNTAX_OK"

[[ "$COMP" =~ ^[0-9]{6}$ ]] || {
  echo "Uso: $0 YYYYMM" >&2
  exit 2
}

# Referencia oficial das Regioes Administrativas do DF.
"$ROOT/ops/ibge-localidades-complete.sh"

# Reconstroi contexto municipal com nomes das cinco Grandes Regioes.
python3 "$ROOT/etl/parquet_duckdb/reference/build_municipio_contexto.py"

for f in \
  "$STATE/base_complete_${COMP}.ok" \
  "$STATE/qc_bronze_${COMP}.ok" \
  "$STATE/qc_territorio_${COMP}.ok" \
  "$STATE/qc_unidade_${COMP}.ok"
do
  [[ -f "$f" ]] || { echo "ERRO: gate ausente: $f" >&2; exit 20; }
done

python3 "$ROOT/etl/parquet_duckdb/cnes/build_df_ra_crosswalk.py" --competencia "$COMP"
python3 "$ROOT/etl/parquet_duckdb/reference/build_territorio_conformado.py"
python3 "$ROOT/ops/cnes-profile-bronze.py" --competencia "$COMP"
python3 "$ROOT/etl/parquet_duckdb/cnes/build_silver_current.py" --competencia "$COMP"
python3 "$ROOT/ops/build-cnes-duckdb-views.py"
python3 "$ROOT/ops/qc-cnes-drill-territorial.py"
python3 "$ROOT/ops/cnes-classify-tables.py"
python3 "$ROOT/ops/qc-cnes-global.py" --competencia "$COMP"
python3 "$ROOT/ops/cnes-promote-silver-snapshot.py" --competencia "$COMP"
echo "CNES_SILVER_COMPLETE_OK competencia=$COMP"
