#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YEAR="$(date +%Y)"
ZIP_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --year) YEAR="$2"; shift 2 ;;
    --zip-name) ZIP_NAME="$2"; shift 2 ;;
    -h|--help)
      echo "Uso: ops/territorio-complete.sh [--year AAAA] [--zip-name ARQUIVO.zip]"
      exit 0
      ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

args=(--year "$YEAR")
[[ -n "$ZIP_NAME" ]] && args+=(--zip-name "$ZIP_NAME")

"$ROOT/ops/territorio-acquire.sh" "${args[@]}"
python3 "$ROOT/etl/parquet_duckdb/reference/build_territorio.py"
python3 "$ROOT/etl/parquet_duckdb/reference/build_municipio_contexto.py"
