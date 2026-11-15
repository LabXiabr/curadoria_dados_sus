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

echo "=== CNES 1/2: RAW ==="
out="$("$ROOT/ops/cnes-acquire-base.sh" --competencia "$COMP")"
printf '%s\n' "$out"
comp="$(printf '%s\n' "$out" | sed -nE 's/^CNES_RAW_OK competencia=([0-9]{6}).*/\1/p' | tail -1)"
[[ -n "$comp" ]] || { echo "ERRO: nao foi possivel obter competencia adquirida" >&2; exit 10; }

echo
echo "=== CNES 2/2: BRONZE ==="
python3 "$ROOT/etl/parquet_duckdb/cnes/build_bronze.py" --competencia "$comp"
