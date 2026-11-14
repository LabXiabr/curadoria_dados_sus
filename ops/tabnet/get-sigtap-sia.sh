#!/usr/bin/env bash
set -Eeuo pipefail

OUTDIR="${1:-.}"
URL_SIA="${TABNET_SIA_URL:-http://tabnet.datasus.gov.br/cgi/deftohtm.exe?sia/cnv/qabr.def}"

mkdir -p "$OUTDIR"
ts="$(date +%Y%m%d_%H%M%S)"
meta="$OUTDIR/tabnet_sia_${ts}.meta.tsv"

printf 'extracted_at\turl\tfield\tselect_id\tfile\trows\tsha256\n' > "$meta"

extract_one() {
    local id="$1"
    local name="$2"
    local code_len="$3"
    local dest="$OUTDIR/${name}.tsv"
    local html tmp

    html="$(mktemp)"
    tmp="$(mktemp)"
    trap 'rm -f "$html" "$tmp"' RETURN

    curl --fail --silent --show-error "$URL_SIA" \
      | iconv -f iso-8859-1 -t utf-8 > "$html"

    sed -n "/ID=\"$id\"/,/<\/SELECT>/p" "$html" \
      | grep -i '<OPTION' \
      | sed 's/<[^>]*>//g' \
      | sed 's/^[[:space:]]*//' \
      | python3 -c 'import sys,html; [print(html.unescape(x.strip())) for x in sys.stdin]' \
      | grep -vE 'Todas as categorias|^$' \
      | sort -u > "$tmp"

    {
        printf 'codigo\tdescricao\n'
        awk -v n="$code_len" '
            {
                code=substr($0,1,n)
                desc=substr($0,n+1)
                sub(/^[[:space:]]+/,"",desc)
                gsub(/\t/," ",desc)
                printf "%s\t%s\n",code,desc
            }
        ' "$tmp"
    } > "$dest"

    rows=$(( $(wc -l < "$dest") - 1 ))
    sha="$(sha256sum "$dest" | awk '{print $1}')"

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$(date -Is)" "$URL_SIA" "$name" "$id" "$dest" "$rows" "$sha" >> "$meta"

    echo "$name rows=$rows -> $dest"
}

extract_one S17 grupo 2
extract_one S18 subgrupo 4
extract_one S19 forma 6
extract_one S16 procedimento 10

echo "metadata=$meta"
