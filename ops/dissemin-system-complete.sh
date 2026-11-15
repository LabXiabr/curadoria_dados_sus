#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="BURETA"
SYSTEM=""
EXEC=0
MAX_TABLES=""
COMMON=()
INV=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="$2"; shift 2 ;;
    --system)
      SYSTEM="$2"; COMMON+=("--system" "$2"); INV+=("--system" "$2"); shift 2 ;;
    --subsystem|--from|--to|--schema|--table)
      COMMON+=("$1" "$2"); shift 2 ;;
    --max-tables|--max-files)
      MAX_TABLES="$2"; shift 2 ;;
    --execute)
      EXEC=1; shift ;;
    --force)
      COMMON+=("--force"); shift ;;
    -h|--help)
      cat <<'EOF'
Uso:
  ops/dissemin-system-complete.sh --system SIA|SIH|CIH|CIHA|SIM|SINASC|SINAN [filtros] [--execute]

Fonte da migracao inicial: PostgreSQL bdsus.
DBC/Wine fica fora deste fluxo e serve para recomposicao futura.
EOF
      exit 0 ;;
    *)
      echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$SYSTEM" ]] || { echo "ERRO: --system obrigatorio" >&2; exit 2; }

python3 -m py_compile   "$ROOT/ops/psql-dissemin-inventory.py"   "$ROOT/etl/psql/dissemin/export_bronze.py"   "$ROOT/etl/psql/dissemin/build_silver.py"

python3 "$ROOT/ops/psql-dissemin-inventory.py" --profile "$PROFILE" "${INV[@]}"

ARGS=(--profile "$PROFILE" "${COMMON[@]}")
[[ -n "$MAX_TABLES" ]] && ARGS+=(--max-tables "$MAX_TABLES")

if (( EXEC == 0 )); then
  python3 "$ROOT/etl/psql/dissemin/export_bronze.py" "${ARGS[@]}"
  echo "DISSEMIN_PSQL_DRY_RUN_OK system=$SYSTEM profile=$PROFILE"
  exit 0
fi

python3 "$ROOT/etl/psql/dissemin/export_bronze.py" "${ARGS[@]}" --execute
python3 "$ROOT/etl/psql/dissemin/build_silver.py" "${ARGS[@]}" --execute

echo "DISSEMIN_PSQL_COMPLETE_OK system=$SYSTEM profile=$PROFILE"
