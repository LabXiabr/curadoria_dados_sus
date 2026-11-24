#!/usr/bin/env bash
set -Eeuo pipefail

MODE="dry-run"
DAYS="${DAYS:-7}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) MODE="execute"; shift ;;
    --days) DAYS="$2"; shift 2 ;;
    -h|--help)
      echo "Uso: $0 [--execute] [--days N]"
      echo "Compacta apenas *.log antigos em logs/. Nunca toca state/, *.ok ou TSV."
      exit 0
      ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

is_open(){
  local f="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -t -- "$f" >/dev/null 2>&1
  else
    return 1
  fi
}

collect(){
  local root="$1"
  [[ -d "$root" ]] || return 0
  find "$root" -type f -name '*.log' -mtime "+$DAYS" -print0
}

declare -a files=()
while IFS= read -r -d '' f; do files+=("$f"); done < <(collect "$REPO_ROOT/logs")
while IFS= read -r -d '' f; do files+=("$f"); done < <(collect "$LAKE_ROOT/logs")

echo "LOG_CLEANUP mode=$MODE days=$DAYS candidates=${#files[@]}"
before=0
for f in "${files[@]}"; do
  size=$(stat -c '%s' "$f" 2>/dev/null || echo 0)
  before=$((before+size))
  if is_open "$f"; then
    echo "SKIP_OPEN $f"
    continue
  fi
  if [[ "$MODE" == "execute" ]]; then
    gzip -9 -- "$f"
    echo "GZIP $f"
  else
    echo "PLAN_GZIP $f"
  fi
done

echo "candidate_bytes=$before"
if [[ "$MODE" != "execute" ]]; then
  echo "DRY_RUN: nenhuma alteracao realizada"
else
  echo "LOG_CLEANUP_OK"
fi
