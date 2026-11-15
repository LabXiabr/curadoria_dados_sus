#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FROM=2000
TO=2025

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --to) TO="$2"; shift 2 ;;
    -h|--help)
      echo "Uso: ops/popsvs-complete.sh [--from AAAA] [--to AAAA]"
      exit 0
      ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

"$ROOT/ops/popsvs-acquire.sh" --from "$FROM" --to "$TO"
python3 "$ROOT/etl/parquet_duckdb/reference/build_popsvs.py" --from "$FROM" --to "$TO"
