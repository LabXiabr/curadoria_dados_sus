#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YEAR="$(date +%Y)"
POP_FROM=2000
POP_TO=2025

while [[ $# -gt 0 ]]; do
  case "$1" in
    --year) YEAR="$2"; shift 2 ;;
    --pop-from) POP_FROM="$2"; shift 2 ;;
    --pop-to) POP_TO="$2"; shift 2 ;;
    -h|--help)
      echo "Uso: ops/reference-geography-complete.sh [--year AAAA] [--pop-from AAAA] [--pop-to AAAA]"
      exit 0
      ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

echo "=== 1/3 BASE TERRITORIAL DATASUS ==="
"$ROOT/ops/territorio-complete.sh" --year "$YEAR"

echo
echo "=== 2/3 REGIONALIZACAO DE SAUDE CORRENTE ==="
"$ROOT/ops/regionalizacao-saude-complete.sh"

echo
echo "=== 3/3 POPSVS DETALHADO ==="
"$ROOT/ops/popsvs-complete.sh" --from "$POP_FROM" --to "$POP_TO"

echo
echo "REFERENCE_GEOGRAPHY_COMPLETE_OK"
