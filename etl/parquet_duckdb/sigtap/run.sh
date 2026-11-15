#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PARSER="$ROOT/etl/parquet_duckdb/sigtap/fwf_to_csv.awk"
LAYOUT_NORMALIZER="$ROOT/etl/parquet_duckdb/sigtap/normalize_layout.py"

FTP_BASE="${SIGTAP_FTP_BASE:-ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"

RAW="$LAKE_ROOT/raw/sigtap/zip"
BRONZE="$LAKE_ROOT/bronze/sigtap"
WORKROOT="$LAKE_ROOT/work/sigtap"
STATE="$LAKE_ROOT/state/sigtap"
LOGROOT="$LAKE_ROOT/logs/sigtap"

COMP="latest"
INSPECT=0
KEEP_WORK="${KEEP_WORK:-0}"
OFFLINE="${SIGTAP_OFFLINE:-0}"
SOURCE_ZIP=""

usage() {
    cat <<EOF
Uso:
  $0 [--competencia YYYYMM|latest] [--source-zip ZIP] [--inspect-only] [--offline]

O layout fisico e lido dos arquivos *_layout.txt contidos no proprio ZIP.
Os layouts sao validados (tamanho/inicio/fim/contiguidade) antes da carga.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --competencia) COMP="$2"; shift 2 ;;
        --source-zip) SOURCE_ZIP="$2"; shift 2 ;;
        --inspect-only) INSPECT=1; shift ;;
        --offline) OFFLINE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
    esac
done

for c in bash curl unzip awk sed sort sha256sum iconv duckdb python3; do
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

remote_names="$(mktemp)"
trap 'rm -f "$remote_names"' EXIT

ftp_ok=0
if (( OFFLINE == 0 )); then
    if curl --fail --silent --show-error --list-only "$FTP_BASE/" \
        | tr -d '\r' \
        | grep -E '^TabelaUnificada_[0-9]{6}.*\.zip$' \
        | sort -u > "$remote_names"; then
        ftp_ok=1
    fi
fi

if [[ -n "$SOURCE_ZIP" ]]; then
    [[ "$SOURCE_ZIP" == "$(basename "$SOURCE_ZIP")" ]] || {
        echo "ERRO: --source-zip deve ser apenas nome de arquivo: $SOURCE_ZIP" >&2
        exit 4
    }
    [[ "$SOURCE_ZIP" =~ ^TabelaUnificada_([0-9]{6}).*\.zip$ ]] || {
        echo "ERRO: nome SIGTAP invalido: $SOURCE_ZIP" >&2
        exit 4
    }
    selected="$SOURCE_ZIP"
    source_comp="${BASH_REMATCH[1]}"
    if [[ "$COMP" != "latest" && "$COMP" != "$source_comp" ]]; then
        echo "ERRO: competencia $COMP diverge de --source-zip $SOURCE_ZIP" >&2
        exit 4
    fi
elif [[ "$COMP" == "latest" ]]; then
    if (( ftp_ok == 1 )); then
        selected="$(
            sed -nE 's/^(TabelaUnificada_([0-9]{6}).*\.zip)$/\2\t\1/p' "$remote_names" \
            | sort -t $'\t' -k1,1n -k2,2 \
            | tail -1 \
            | cut -f2
        )"
    else
        selected="$(
            find "$RAW" -maxdepth 1 -type f -name 'TabelaUnificada_*.zip' -printf '%f\n' \
            | sed -nE 's/^(TabelaUnificada_([0-9]{6}).*\.zip)$/\2\t\1/p' \
            | sort -t $'\t' -k1,1n -k2,2 \
            | tail -1 \
            | cut -f2
        )"
    fi
else
    selected="$(
        find "$RAW" -maxdepth 1 -type f -name "TabelaUnificada_${COMP}*.zip" -printf '%f\n' \
        | sort \
        | tail -1
    )"
    if [[ -z "$selected" && "$ftp_ok" == "1" ]]; then
        selected="$(grep -E "^TabelaUnificada_${COMP}.*\.zip$" "$remote_names" | sort | tail -1 || true)"
    fi
fi
[[ -n "${selected:-}" ]] || {
    echo "ERRO: competencia nao encontrada: $COMP" >&2
    exit 4
}

competencia="$(printf '%s\n' "$selected" | sed -nE 's/^TabelaUnificada_([0-9]{6}).*/\1/p')"
zip="$RAW/$selected"

if [[ ! -f "$zip" ]]; then
    (( ftp_ok == 1 )) || {
        echo "ERRO: ZIP local ausente e FTP indisponivel: $selected" >&2
        exit 5
    }
    partial="$zip.partial.$$"
    curl --fail --location --silent --show-error --retry 4 --retry-delay 3 \
        --remote-time --output "$partial" "$FTP_BASE/$selected"
    unzip -tq "$partial" >/dev/null
    mv "$partial" "$zip"
fi

unzip -tq "$zip" >/dev/null
zip_sha="$(sha256sum "$zip" | awk '{print $1}')"

echo "Arquivo: $selected"
echo "Competencia: $competencia"
echo "SHA256 ZIP: $zip_sha"

work="$WORKROOT/${competencia}_${ts}"
mkdir -p "$work/extract"
unzip -q "$zip" -d "$work/extract"

registry="$STATE/layout_registry_${competencia}_${ts}.tsv"
report="$STATE/layout_${competencia}_${ts}.tsv"
resolved="$work/resolved.tsv"
layoutnorm="$work/layout_norm"
mkdir -p "$layoutnorm"

printf 'competencia\ttable\tordinal\tcolumn\twidth\tstart\tend\tsource_type\tsource_zip\tsha256_zip\n' > "$registry"
printf 'table\tfile\trows\tmin_len\tmax_len\texpected_len\tlayout_file\tstatus\n' > "$report"
printf 'table\tfile\trows\twidths\tfields\texpected_len\tstatus\n' > "$resolved"

layout_issues=0

while IFS= read -r -d '' lf; do
    base="$(basename "$lf")"
    table="$(printf '%s' "${base%_layout.*}" | tr '[:upper:]' '[:lower:]')"

    norm="$layoutnorm/$table.tsv"
    if ! python3 "$LAYOUT_NORMALIZER" "$lf" > "$norm"; then
        echo "ERRO layout oficial inconsistente: $base" >&2
        ((layout_issues+=1))
        continue
    fi

    awk -F'\t' -v c="$competencia" -v t="$table" -v z="$selected" -v h="$zip_sha" '
        NR==1 {next}
        {
            printf "%s\t%s\t%d\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n",
                   c,t,NR-1,$1,$2,$3,$4,$5,z,h
        }
    ' "$norm" >> "$registry"
done < <(find "$work/extract" -type f -iname '*_layout.txt' -print0 | sort -z)

(( layout_issues == 0 )) || {
    echo "ERRO: $layout_issues layouts oficiais invalidos." >&2
    exit 6
}

issues=0
recognized=0
metadata=0

while IFS= read -r -d '' txt; do
    base="$(basename "$txt")"
    table="$(printf '%s' "${base%.*}" | tr '[:upper:]' '[:lower:]')"

    case "$table" in
        layout|leia_me|*_layout)
            ((metadata+=1))
            continue
            ;;
    esac

    read -r rows minlen maxlen < <(
        LC_ALL=C awk '
            {
                sub(/\r$/, "", $0)
                if (length($0)==0) next
                l=length($0)
                n+=1
                if (n==1 || l<mn) mn=l
                if (n==1 || l>mx) mx=l
            }
            END {print n+0, mn+0, mx+0}
        ' "$txt"
    )

    lf="$(find "$work/extract" -type f -iname "${table}_layout.txt" -print -quit)"

    if [[ -z "$lf" ]]; then
        printf '%s\t%s\t%s\t%s\t%s\t\t\tmissing_official_layout\n' \
            "$table" "$base" "$rows" "$minlen" "$maxlen" >> "$report"
        printf '%s\t%s\t%s\t\t\t\tmissing_official_layout\n' \
            "$table" "$base" "$rows" >> "$resolved"
        ((issues+=1))
        continue
    fi

    norm="$layoutnorm/$table.tsv"
    [[ -s "$norm" ]] || {
        printf '%s\t%s\t%s\t%s\t%s\t\t\tmissing_normalized_layout\n' \
            "$table" "$base" "$rows" "$minlen" "$maxlen" >> "$report"
        printf '%s\t%s\t%s\t\t\t\tmissing_normalized_layout\n' \
            "$table" "$base" "$rows" >> "$resolved"
        ((issues+=1))
        continue
    }

    widths="$(awk -F'\t' 'NR>1 {if (seen) printf "|"; printf "%s",$2; seen=1}' "$norm")"
    fields="$(awk -F'\t' 'NR>1 {if (seen) printf "|"; printf "%s",$1; seen=1}' "$norm")"
    expected="$(awk -F'\t' 'NR>1 {v=$4+0} END {print v+0}' "$norm")"
    last_start="$(awk -F'\t' 'NR>1 {v=$3+0} END {print v+0}' "$norm")"

    if [[ "$rows" == "0" ]]; then
        status="ok"
    elif [[ "$minlen" == "$expected" && "$maxlen" == "$expected" ]]; then
        status="ok"
    elif (( maxlen <= expected && minlen >= last_start - 1 )); then
        # Alguns TXT oficiais omitem apenas o padding de espacos a direita
        # do ultimo campo. Isso e lossless porque o parser/QC normalizam
        # espacos terminais do campo, sem aceitar truncamento de campos
        # anteriores.
        status="ok_right_trimmed"
    else
        status="width_mismatch"
        ((issues+=1))
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$table" "$base" "$rows" "$minlen" "$maxlen" "$expected" "$(basename "$lf")" "$status" >> "$report"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$table" "$base" "$rows" "$widths" "$fields" "$expected" "$status" >> "$resolved"

    [[ "$status" == "ok" || "$status" == "ok_right_trimmed" ]] && ((recognized+=1))
done < <(find "$work/extract" -type f -iname '*.txt' -print0 | sort -z)

echo
echo "Registro oficial de layouts: $registry"
echo "Relatorio: $report"
awk -F'\t' 'NR==1 || $8!="ok"' "$report" | column -s $'\t' -t || true
echo "Tabelas de dados reconhecidas: $recognized"
echo "Metadados/documentacao ignorados como dados: $metadata"
echo "Problemas: $issues"

if (( INSPECT == 1 )); then
    echo "Modo inspect-only: nenhum Parquet publicado."
    [[ "$KEEP_WORK" == "1" ]] || rm -rf "$work"
    exit $(( issues == 0 ? 0 : 7 ))
fi

(( issues == 0 )) || {
    echo "ERRO: Bronze bloqueada por layout/arquivo divergente." >&2
    exit 7
}

manifest="$STATE/bronze_${competencia}_${ts}.tsv"
printf 'table\tcompetencia\trows_source\trows_parquet\tparquet\tsource_zip\tsha256_zip\n' > "$manifest"

while IFS=$'\t' read -r table file rows widths fields expected status; do
    [[ "$table" == "table" ]] && continue
    [[ "$status" == "ok" || "$status" == "ok_right_trimmed" ]] || continue

    txt="$(find "$work/extract" -type f -iname "${table}.txt" -print -quit)"
    [[ -n "$txt" ]] || exit 8

    latin="$work/${table}.latin1.csv"
    utf8="$work/${table}.utf8.csv"

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
                delim=',',
                header=true,
                all_varchar=true
            )
        )
        TO '$partial'
        (FORMAT PARQUET, COMPRESSION ZSTD);
    "

    rows_parquet="$(duckdb -csv -noheader -c "SELECT count(*) FROM read_parquet('$partial');" | tr -d '\r')"
    [[ "$rows" == "$rows_parquet" ]] || {
        echo "ERRO QC $table: TXT=$rows Parquet=$rows_parquet" >&2
        exit 9
    }

    mv -f "$partial" "$dest"

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$table" "$competencia" "$rows" "$rows_parquet" \
        "$dest" "$selected" "$zip_sha" >> "$manifest"

    rm -f "$latin" "$utf8"
    echo "OK $table rows=$rows"
done < "$resolved"

[[ "$KEEP_WORK" == "1" ]] || rm -rf "$work"

echo
echo "Bronze publicada."
echo "Manifesto: $manifest"
echo "Fim: $(date -Is)"
