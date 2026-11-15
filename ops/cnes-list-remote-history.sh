#!/usr/bin/env bash
set -Eeuo pipefail

FTP_BASE="${CNES_FTP_BASE:-ftp://ftp.datasus.gov.br/cnes}"
MIN_COMP="${CNES_BASE_MIN_COMP:-201706}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
STATE="$LAKE_ROOT/state/cnes"
RAW="$LAKE_ROOT/raw/cnes/base_dados"
mkdir -p "$STATE"

for c in curl grep sed sort wc date awk; do
  command -v "$c" >/dev/null 2>&1 || {
    echo "ERRO: comando ausente: $c" >&2
    exit 3
  }
done

[[ "$MIN_COMP" =~ ^[0-9]{6}$ ]] || {
  echo "ERRO: CNES_BASE_MIN_COMP invalida: $MIN_COMP" >&2
  exit 2
}

ts="$(date +%Y%m%d_%H%M%S)"
out="$STATE/remote_history_${ts}.tsv"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

curl --fail --silent --show-error --list-only "$FTP_BASE/"   | tr -d '\r'   | grep -Ei '^BASE_DE_DADOS_CNES_[0-9]{6}\.ZIP$'   | sort -u > "$tmp"

{
  printf 'competencia\tfilename\tofficial_supported\tlocal_raw\tbase_complete\tqc_global\tsilver_snapshot\n'
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    comp="$(printf '%s\n' "$file" | sed -nE 's/^BASE_DE_DADOS_CNES_([0-9]{6})\.ZIP$/\1/Ip')"
    [[ -n "$comp" ]] || continue

    supported=0
    [[ "$comp" >= "$MIN_COMP" ]] && supported=1

    raw=0
    base=0
    global=0
    snap=0
    [[ -f "$RAW/competencia=$comp/$file" ]] && raw=1
    [[ -f "$STATE/base_complete_$comp.ok" ]] && base=1
    [[ -f "$STATE/qc_global_$comp.ok" ]] && global=1
    [[ -f "$STATE/silver_snapshot_$comp.ok" ]] && snap=1

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n'       "$comp" "$file" "$supported" "$raw" "$base" "$global" "$snap"
  done < "$tmp"
} > "$out"

count_listed="$(tail -n +2 "$out" | wc -l | tr -d ' ')"
count_supported="$(awk -F $'\t' 'NR>1 && $3==1 {n++} END{print n+0}' "$out")"
first_listed="$(tail -n +2 "$out" | cut -f1 | head -1)"
first_supported="$(awk -F $'\t' 'NR>1 && $3==1 {print $1; exit}' "$out")"
last="$(tail -n +2 "$out" | cut -f1 | tail -1)"

marker="$STATE/remote_history_current.ok"
{
  echo "timestamp=$ts"
  echo "source=$FTP_BASE/"
  echo "official_min_competencia=$MIN_COMP"
  echo "count_listed=$count_listed"
  echo "count_supported=$count_supported"
  echo "first_listed=$first_listed"
  echo "first_supported=$first_supported"
  echo "last=$last"
  echo "report=$out"
  echo "status=complete"
} > "$marker"

echo "CNES_REMOTE_HISTORY_OK listed=$count_listed supported=$count_supported first_listed=$first_listed first_supported=$first_supported last=$last report=$out"
column -ts $'\t' "$out"
