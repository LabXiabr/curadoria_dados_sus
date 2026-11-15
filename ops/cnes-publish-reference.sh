#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMP="${1:-202610}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"

[[ "$COMP" =~ ^[0-9]{6}$ ]] || {
  echo "Uso: $0 YYYYMM" >&2
  exit 2
}

for f in   "$LAKE_ROOT/state/cnes/base_complete_${COMP}.ok"   "$LAKE_ROOT/state/cnes/qc_global_${COMP}.ok"   "$LAKE_ROOT/state/cnes/silver_snapshot_${COMP}.ok"
do
  [[ -f "$f" ]] || {
    echo "ERRO: gate ausente: $f" >&2
    exit 20
  }
done

python3 -m py_compile   "$ROOT/ops/publish-parquet-artifacts.py"   "$ROOT/ops/cnes-promote-silver-snapshot.py"

"$ROOT/ops/publish-parquet-artifacts.py" --dataset cnes_bronze_reference
"$ROOT/ops/publish-parquet-artifacts.py" --dataset cnes_silver_reference

echo "CNES_REFERENCE_PUBLICATION_OK competencia=$COMP"
echo "bronze=https://dados.labx.ia.br/files/bronze/cnes/"
echo "silver=https://dados.labx.ia.br/files/silver/cnes/"
