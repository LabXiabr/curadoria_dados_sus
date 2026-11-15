#!/usr/bin/env bash
set -Eeuo pipefail

FTP_BASE="${CNES_FTP_BASE:-ftp://ftp.datasus.gov.br/cnes}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
STATE="$LAKE_ROOT/state/cnes"
RAW="$LAKE_ROOT/raw/cnes/base_dados"
mkdir -p "$STATE"

for c in curl grep sed sort wc date; do
  command -v "$c" >/dev/null 2>&1 || {
    echo "ERRO: comando ausente: $c" >&2
    exit 3
  }
done

ts="$(date +%Y%m%d_%H%M%S)"
out="$STATE/remote_history_${ts}.tsv"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

curl --fail --silent --show-error --list-only "$FTP_BASE/"   | tr -d '\r'   | grep -Ei '^BASE_DE_DADOS_CNES_[0-9]{6}\.ZIP$'   | sort -u > "$tmp"

{
  printf 'competencia\tfilename\tlocal_raw\tbase_complete\tqc_global\tsilver_snapshot\n'
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    comp="$(printf '%s\n' "$file" | sed -nE 's/^BASE_DE_DADOS_CNES_([0-9]{6})\.ZIP$/\1/Ip')"
    [[ -n "$comp" ]] || continue
    raw=0
    base=0
    global=0
    snap=0
    [[ -f "$RAW/competencia=$comp/$file" ]] && raw=1
    [[ -f "$STATE/base_complete_$comp.ok" ]] && base=1
    [[ -f "$STATE/qc_global_$comp.ok" ]] && global=1
    [[ -f "$STATE/silver_snapshot_$comp.ok" ]] && snap=1
    printf '%s\t%s\t%s\t%s\t%s\t%s\n'       "$comp" "$file" "$raw" "$base" "$global" "$snap"
  done < "$tmp"
} > "$out"

count="$(tail -n +2 "$out" | wc -l | tr -d ' ')"
first="$(tail -n +2 "$out" | cut -f1 | head -1)"
last="$(tail -n +2 "$out" | cut -f1 | tail -1)"

marker="$STATE/remote_history_current.ok"
{
  echo "timestamp=$ts"
  echo "source=$FTP_BASE/"
  echo "count=$count"
  echo "first=$first"
  echo "last=$last"
  echo "report=$out"
  echo "status=complete"
} > "$marker"

echo "CNES_REMOTE_HISTORY_OK count=$count first=$first last=$last report=$out"
column -ts $'\t' "$out"
