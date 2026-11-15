#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMP="${1:-202610}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
STATE="$LAKE_ROOT/state/cnes"
mkdir -p "$STATE"

"$ROOT/ops/cnes-preflight.sh"

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
echo "CNES_SILVER_COMPLETE_OK competencia=$COMP"
