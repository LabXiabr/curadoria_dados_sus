#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
LAYOUT="$ROOT/systems/sigtap/layouts/fwf.tsv"
PARSER="$ROOT/etl/parquet_duckdb/sigtap/fwf_to_tsv.awk"

FTP_BASE="${SIGTAP_FTP_BASE:-ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"

RAW="$LAKE_ROOT/raw/sigtap/zip"
BRONZE="$LAKE_ROOT/bronze/sigtap"
WORKROOT="$LAKE_ROOT/work/sigtap"
STATE="$LAKE_ROOT/state/sigtap"
LOGROOT="$LAKE_ROOT/logs/sigtap"

COMP="latest"
INSPECT=0
ALLOW_PARTIAL=0
KEEP_WORK="${KEEP_WORK:-0}"

usage() {
    cat <<EOF
Uso:
  $0 [--competencia YYYYMM|latest] [--inspect-only] [--allow-partial]

Por padrao, falha antes de publicar se houver TXT sem layout conhecido
ou largura de linha diferente do contrato.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --competencia) COMP="$2"; shift 2 ;;
        --inspect-only) INSPECT=1; shift ;;
        --allow-partial) ALLOW_PARTIAL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
    esac
done

for c in bash curl unzip awk sed sort sha256sum iconv duckdb; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 3
    }
done

mkdir -p "$RAW" "$BRONZE" "$WORKROOT" "$STATE" "$LOGROOT"

ts="$(date +%Y%m%d_%H%M%S)"
log="$LOGROOT/sigtap_${ts}.log"
exec > >(tee -a "$log") 2>&1

echo "Inicio: $(date -Is)"
echo "Competencia solicitada: $COMP"

local_pick=""
if [[ "$COMP" != "latest" ]]; then
    local_pick="$(find "$RAW" -maxdepth 1 -type f -name "TabelaUnificada_${COMP}_*.zip" -printf '%f\n' 2>/dev/null | sort | tail -1 || true)"
fi

remote_names="$(mktemp)"
trap 'rm -f "$remote_names"' EXIT

if curl --fail --silent --show-error --list-only "$FTP_BASE/" \
    | tr -d '\r' \
    | grep -E '^TabelaUnificada_[0-9]{6}.*\.zip$' \
    | sort -u > "$remote_names"; then
    :
elif [[ -z "$local_pick" ]]; then
    echo "ERRO: FTP indisponivel e nao existe ZIP local para $COMP" >&2
    exit 4
fi

if [[ "$COMP" == "latest" ]]; then
    selected="$(
        sed -nE 's/^(TabelaUnificada_([0-9]{6}).*\.zip)$/\2\t\1/p' "$remote_names" \
        | sort -t $'\t' -k1,1n -k2,2 \
        | tail -1 \
        | cut -f2
    )"
elif [[ -n "$local_pick" ]]; then
    selected="$local_pick"
else
    selected="$(grep -E "^TabelaUnificada_${COMP}.*\.zip$" "$remote_names" | sort | tail -1 || true)"
fi

[[ -n "$selected" ]] || {
    echo "ERRO: competencia nao encontrada: $COMP" >&2
    exit 5
}

competencia="$(printf '%s\n' "$selected" | sed -nE 's/^TabelaUnificada_([0-9]{6}).*/\1/p')"
zip="$RAW/$selected"

echo "Arquivo: $selected"
echo "Competencia: $competencia"

if [[ ! -f "$zip" ]]; then
    partial="$zip.partial.$$"
    echo "Baixando para Raw..."
    curl --fail --location --silent --show-error --retry 4 --retry-delay 3 \
        --remote-time --output "$partial" "$FTP_BASE/$selected"
    unzip -tq "$partial" >/dev/null
    mv "$partial" "$zip"
fi

unzip -tq "$zip" >/dev/null
zip_sha="$(sha256sum "$zip" | awk '{print $1}')"
echo "SHA256 ZIP: $zip_sha"

work="$WORKROOT/${competencia}_${ts}"
mkdir -p "$work/extract"
unzip -q "$zip" -d "$work/extract"

report="$STATE/layout_${competencia}_${ts}.tsv"
printf 'table\tfile\trows\tmin_len\tmax_len\texpected_len\tlayout_source\tstatus\n' > "$report"

issues=0
recognized=0

while IFS= read -r -d '' txt; do
    base="$(basename "$txt")"
    table="$(printf '%s' "${base%.*}" | tr '[:upper:]' '[:lower:]')"

    read -r rows minlen maxlen < <(
        LC_ALL=C awk '
            {
                sub(/\r$/, "", $0)
                l=length($0)
                if (NR==1 || l<mn) mn=l
                if (NR==1 || l>mx) mx=l
            }
            END {print NR+0, mn+0, mx+0}
        ' "$txt"
    )

    # TXT de documentacao/layout pertencem ao pacote oficial,
    # mas nao sao tabelas de dados da Bronze.
    case "$table" in
        layout|leia_me|*_layout)
            printf '%s\t%s\t%s\t%s\t%s\t\t\tignored_metadata\n' \
                "$table" "$base" "$rows" "$minlen" "$maxlen" >> "$report"
            continue
            ;;
    esac

    layout_row="$(
        awk -F'\t' -v t="$table" -v c="$competencia" '
            NR>1 && $1==t && c>=$2 && c<=$3 {print; exit}
        ' "$LAYOUT"
    )"

    if [[ -z "$layout_row" ]]; then
        printf '%s\t%s\t%s\t%s\t%s\t\t\tunknown_layout\n' \
            "$table" "$base" "$rows" "$minlen" "$maxlen" >> "$report"
        ((issues+=1))
        continue
    fi

    expected="$(printf '%s\n' "$layout_row" | cut -f6)"
    source="$(printf '%s\n' "$layout_row" | cut -f7)"

    # Arquivo de dados vazio e valido: representa conjunto vazio.
    if [[ "$rows" == "0" ]]; then
        printf '%s\t%s\t0\t0\t0\t%s\t%s\tok\n' \
            "$table" "$base" "$expected" "$source" >> "$report"
        ((recognized+=1))
        continue
    fi

    if [[ "$minlen" != "$expected" || "$maxlen" != "$expected" ]]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\twidth_mismatch\n' \
            "$table" "$base" "$rows" "$minlen" "$maxlen" "$expected" "$source" >> "$report"
        ((issues+=1))
        continue
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\tok\n' \
        "$table" "$base" "$rows" "$minlen" "$maxlen" "$expected" "$source" >> "$report"
    ((recognized+=1))
done < <(find "$work/extract" -type f -iname '*.txt' -print0 | sort -z)

echo
echo "Relatorio de layout: $report"
awk -F'\t' 'NR==1 || ($8!="ok" && $8!="ignored_metadata")' "$report" | column -s $'\t' -t || true
echo "Reconhecidos: $recognized"
echo "Problemas: $issues"

if (( INSPECT == 1 )); then
    echo "Modo inspect-only: nenhum Parquet publicado."
    [[ "$KEEP_WORK" == "1" ]] || rm -rf "$work"
    exit 0
fi

if (( issues > 0 && ALLOW_PARTIAL == 0 )); then
    echo "ERRO: Bronze completa bloqueada por layouts desconhecidos/divergentes." >&2
    echo "Use o relatorio para atualizar systems/sigtap/layouts/fwf.tsv." >&2
    exit 6
fi

manifest="$STATE/bronze_${competencia}_${ts}.tsv"
printf 'table\tcompetencia\trows_source\trows_parquet\tparquet\tsource_zip\tsha256_zip\n' > "$manifest"

while IFS=$'\t' read -r table file rows minlen maxlen expected source status; do
    [[ "$table" == "table" ]] && continue
    [[ "$status" == "ok" ]] || continue

    txt="$(find "$work/extract" -type f -iname "${table}.txt" -print -quit)"
    [[ -n "$txt" ]] || {
        echo "ERRO: arquivo nao localizado para $table" >&2
        exit 7
    }

    layout_row="$(
        awk -F'\t' -v t="$table" -v c="$competencia" '
            NR>1 && $1==t && c>=$2 && c<=$3 {print; exit}
        ' "$LAYOUT"
    )"

    widths="$(printf '%s\n' "$layout_row" | cut -f4)"
    fields="$(printf '%s\n' "$layout_row" | cut -f5)"

    latin="$work/${table}.latin1.tsv"
    utf8="$work/${table}.utf8.tsv"

    LC_ALL=C awk -v widths="$widths" -v fields="$fields" -f "$PARSER" "$txt" > "$latin"
    iconv -f ISO-8859-1 -t UTF-8 "$latin" > "$utf8"

    destdir="$BRONZE/$table/competencia=$competencia"
    mkdir -p "$destdir"
    dest="$destdir/part-000.parquet"
    partial="$dest.partial.$$"

    rm -f "$partial"

    duckdb -c "
        COPY (
            SELECT *,
                   '$competencia'::VARCHAR AS _source_competencia,
                   '$selected'::VARCHAR AS _source_zip,
                   '$zip_sha'::VARCHAR AS _source_sha256,
                   current_timestamp AS _ingested_at
            FROM read_csv(
                '$utf8',
                delim='	',
                header=true,
                all_varchar=true,
                quote='',
                escape=''
            )
        )
        TO '$partial'
        (FORMAT PARQUET, COMPRESSION ZSTD);
    "

    rows_parquet="$(duckdb -csv -noheader -c "SELECT count(*) FROM read_parquet('$partial');" | tr -d '\r')"

    if [[ "$rows" != "$rows_parquet" ]]; then
        echo "ERRO QC $table: TXT=$rows Parquet=$rows_parquet" >&2
        exit 8
    fi

    mv -f "$partial" "$dest"

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$table" "$competencia" "$rows" "$rows_parquet" \
        "$dest" "$selected" "$zip_sha" >> "$manifest"

    rm -f "$latin" "$utf8"
    echo "OK $table rows=$rows -> $dest"
done < "$report"

[[ "$KEEP_WORK" == "1" ]] || rm -rf "$work"

echo
echo "Bronze publicada."
echo "Manifesto: $manifest"
echo "Fim: $(date -Is)"
