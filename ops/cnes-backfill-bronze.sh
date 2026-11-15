#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
STATE="$LAKE_ROOT/state/cnes"

FROM=""
TO=""
EXECUTE=0
MAX=0

usage() {
  cat <<'USAGE'
Uso:
  ops/cnes-backfill-bronze.sh --from YYYYMM --to YYYYMM [--execute] [--max N]

Sem --execute, apenas imprime o plano.
O backfill cobre Raw + Bronze + QCs de base. Nao executa Silver historica.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --to) TO="$2"; shift 2 ;;
    --max) MAX="$2"; shift 2 ;;
    --execute) EXECUTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
  esac
done

[[ "$FROM" =~ ^[0-9]{6}$ && "$TO" =~ ^[0-9]{6}$ ]] || {
  echo "ERRO: --from e --to devem ser YYYYMM" >&2
  exit 2
}

"$ROOT/ops/cnes-list-remote-history.sh" >/dev/null

remote_marker="$STATE/remote_history_current.ok"
report="$(sed -n 's/^report=//p' "$remote_marker" | head -1)"
[[ -f "$report" ]] || {
  echo "ERRO: inventario remoto ausente" >&2
  exit 3
}

mapfile -t comps < <(
  awk -F $'\t' -v a="$FROM" -v b="$TO" '
    NR>1 && $1>=a && $1<=b && $4!=1 {print $1}
  ' "$report" | sort
)

if (( MAX > 0 && ${#comps[@]} > MAX )); then
  comps=("${comps[@]:0:MAX}")
fi

echo "CNES_BACKFILL_PLAN from=$FROM to=$TO missing_base_complete=${#comps[@]} execute=$EXECUTE"
printf '%s\n' "${comps[@]}"

if (( EXECUTE == 0 )); then
  echo "DRY_RUN: use --execute para baixar e construir Raw/Bronze."
  exit 0
fi

for comp in "${comps[@]}"; do
  echo
  echo "=== CNES BACKFILL $comp ==="
  "$ROOT/ops/cnes-base-complete.sh" --competencia "$comp"
done

"$ROOT/ops/cnes-inventory-history.py"
echo "CNES_BACKFILL_BRONZE_OK processed=${#comps[@]}"
