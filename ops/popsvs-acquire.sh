#!/usr/bin/env bash
set -Eeuo pipefail

FTP_BASE="${POPSVS_FTP_BASE:-ftp://ftp.datasus.gov.br/dissemin/publicos/IBGE/POPSVS}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
FROM=2000
TO=2025

usage() {
  echo "Uso: ops/popsvs-acquire.sh [--from AAAA] [--to AAAA]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --to) TO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
  esac
done

[[ "$FROM" =~ ^[0-9]{4}$ && "$TO" =~ ^[0-9]{4}$ ]] || {
  echo "ERRO: anos invalidos" >&2
  exit 2
}
(( FROM <= TO )) || { echo "ERRO: --from > --to" >&2; exit 2; }

for c in curl unzip sha256sum stat; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done

RAW="$LAKE_ROOT/raw/reference/populacao_popsvs"
STATE="$LAKE_ROOT/state/reference"
mkdir -p "$RAW" "$STATE"

report="$STATE/popsvs_acquire_$(date +%Y%m%d_%H%M%S).tsv"
printf 'ano\tfile\tbytes\tsha256\tstatus\tpath\n' > "$report"

fail=0
for ((year=FROM; year<=TO; year++)); do
  yy="$(printf '%02d' $((year % 100)))"
  file="POPSBR${yy}.zip"
  url="$FTP_BASE/$file"
  destdir="$RAW/ano=$year"
  dest="$destdir/$file"
  mkdir -p "$destdir"

  if [[ ! -f "$dest" ]]; then
    partial="$dest.partial.$$"
    rm -f "$partial"
    echo "DOWNLOAD $year $url"
    if ! curl --fail --location --silent --show-error --retry 4 --retry-delay 3       --remote-time --output "$partial" "$url"; then
      echo "ERRO download $year" >&2
      rm -f "$partial"
      printf '%s\t%s\t\t\tfailed_download\t%s\n' "$year" "$file" "$dest" >> "$report"
      ((fail+=1))
      continue
    fi
    if ! unzip -tq "$partial" >/dev/null; then
      echo "ERRO ZIP $year" >&2
      rm -f "$partial"
      printf '%s\t%s\t\t\tfailed_zip\t%s\n' "$year" "$file" "$dest" >> "$report"
      ((fail+=1))
      continue
    fi
    mv "$partial" "$dest"
  else
    unzip -tq "$dest" >/dev/null
    echo "RAW_EXISTENTE $year $dest"
  fi

  sha="$(sha256sum "$dest" | awk '{print $1}')"
  bytes="$(stat -c %s "$dest")"
  marker="$STATE/popsvs_${year}.raw.ok"
  {
    echo "ano=$year"
    echo "timestamp=$(date -Is)"
    echo "source=$url"
    echo "file=$file"
    echo "bytes=$bytes"
    echo "sha256=$sha"
    echo "path=$dest"
  } > "$marker"
  printf '%s\t%s\t%s\t%s\tok\t%s\n' "$year" "$file" "$bytes" "$sha" "$dest" >> "$report"
done

echo "Relatorio: $report"
(( fail == 0 )) || { echo "POPSVS_RAW_INCOMPLETA falhas=$fail" >&2; exit 20; }
echo "POPSVS_RAW_OK anos=$((TO-FROM+1)) from=$FROM to=$TO"
