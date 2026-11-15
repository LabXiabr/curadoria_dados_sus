#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMP="latest"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --competencia) COMP="$2"; shift 2 ;;
        -h|--help)
            echo "Uso: ops/cnes-base-complete.sh [--competencia YYYYMM|latest]"
            exit 0
            ;;
        *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
    esac
done

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
STATE="$LAKE_ROOT/state/cnes"
mkdir -p "$STATE"

echo "=== CNES 0/4: PREFLIGHT ==="
"$ROOT/ops/cnes-preflight.sh"

echo
echo "=== CNES 1/4: RAW ==="
out="$("$ROOT/ops/cnes-acquire-base.sh" --competencia "$COMP")"
printf '%s\n' "$out"
comp="$(printf '%s\n' "$out" | sed -nE 's/^CNES_RAW_OK competencia=([0-9]{6}).*/\1/p' | tail -1)"
[[ -n "$comp" ]] || { echo "ERRO: nao foi possivel obter competencia adquirida" >&2; exit 10; }

echo
echo "=== CNES 2/4: BRONZE ==="
python3 "$ROOT/etl/parquet_duckdb/cnes/build_bronze.py" --competencia "$comp"

echo
echo "=== CNES 3/4: QC TERRITORIAL ==="
python3 "$ROOT/ops/qc-cnes-territorio.py" --competencia "$comp"

echo
echo "=== CNES 4/4: QC CHAVES CO_UNIDADE/CO_CNES ==="
python3 "$ROOT/ops/qc-cnes-unidade.py" --competencia "$comp"

echo
TERR_GATE="$LAKE_ROOT/state/reference/territorio_current_complete.ok"
terr_snapshot="$(sed -n 's/^snapshot=//p' "$TERR_GATE" | head -1)"
marker="$STATE/base_complete_${comp}.ok"
{
    echo "competencia=$comp"
    echo "timestamp=$(date -Is)"
    echo "territorio_snapshot=$terr_snapshot"
    echo "raw_marker=$STATE/raw_base_${comp}.ok"
    echo "bronze_marker=$STATE/qc_bronze_${comp}.ok"
    echo "territorio_qc_marker=$STATE/qc_territorio_${comp}.ok"
    echo "unidade_qc_marker=$STATE/qc_unidade_${comp}.ok"
    echo "status=complete"
} > "$marker"

echo "CNES_BASE_COMPLETE_OK competencia=$comp marker=$marker"
