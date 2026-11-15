#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEM=""
DRY=0
BRONZE_ARGS=()
SILVER_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system)
      SYSTEM="$2"
      BRONZE_ARGS+=("$1" "$2")
      SILVER_ARGS+=("$1" "$2")
      shift 2
      ;;
    --max-files)
      BRONZE_ARGS+=("$1" "$2")
      shift 2
      ;;
    --dry-run)
      DRY=1
      BRONZE_ARGS+=("$1")
      shift
      ;;
    *)
      BRONZE_ARGS+=("$1")
      SILVER_ARGS+=("$1")
      shift
      ;;
  esac
done

[[ "$SYSTEM" == "SIA" || "$SYSTEM" == "SIH" ]] || {
  echo "Uso: $0 --system SIA|SIH [--subsystem X] [--uf XX] [--from YYYYMM] [--to YYYYMM] [--max-files N]" >&2
  exit 2
}

python3 -m py_compile \
  "$ROOT/etl/parquet_duckdb/dissemin/build_dbc_bronze.py" \
  "$ROOT/etl/parquet_duckdb/dissemin/build_dbc_silver.py"

python3 "$ROOT/etl/parquet_duckdb/dissemin/build_dbc_bronze.py" "${BRONZE_ARGS[@]}"
if (( DRY == 1 )); then
  echo "DISSEMIN_SYSTEM_DRY_RUN_OK system=$SYSTEM"
  exit 0
fi
"$ROOT/ops/dissemin-dbc-preflight.sh"
python3 "$ROOT/etl/parquet_duckdb/dissemin/build_dbc_silver.py" "${SILVER_ARGS[@]}"

echo "DISSEMIN_SYSTEM_COMPLETE_OK system=$SYSTEM"
