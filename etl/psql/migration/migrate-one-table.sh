#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ENV_FILE="${CURADORIA_PSQL_ENV:-$HOME/etl_ftp_sus_parquet/.env}"
AUDIT_GLOB="${AUDIT_GLOB:-$HOME/etl_ftp_sus_parquet/state/overnight_*/count_candidates.tsv}"

SCHEMA=""
TABLE=""
DROP=0

usage() {
    cat <<EOF
Uso:
  $0 [--schema SCHEMA --table TABLE] [--drop-after-qc]

Sem schema/table, seleciona a maior tabela com COUNT previamente validado
no count_candidates.tsv (limite daquele inventario).
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --schema) SCHEMA="$2"; shift 2 ;;
        --table) TABLE="$2"; shift 2 ;;
        --drop-after-qc) DROP=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
    esac
done

[[ -f "$ENV_FILE" ]] || {
    echo "ERRO: env nao encontrado: $ENV_FILE" >&2
    exit 40
}

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for v in BURETA_HOST BURETA_DB_PORT BURETA_DB_NAME BURETA_DB_USER BURETA_DB_PASSWORD; do
    [[ -n "${!v:-}" ]] || {
        echo "ERRO: variavel ausente no env: $v" >&2
        exit 41
    }
done

for c in psql duckdb; do
    command -v "$c" >/dev/null || {
        echo "ERRO: comando ausente: $c" >&2
        exit 42
    }
done

if [[ -z "$SCHEMA" || -z "$TABLE" ]]; then
    latest="$(ls -1t $AUDIT_GLOB 2>/dev/null | head -1 || true)"
    [[ -n "$latest" ]] || {
        echo "ERRO: count_candidates.tsv nao encontrado" >&2
        exit 43
    }

    read -r bytes SCHEMA TABLE rows < <(
        awk -F'\t' '
            NR>1 && $8=="ok" && $3 ~ /^[0-9]+$/ {
                print $3 "\t" $1 "\t" $2 "\t" $5
            }
        ' "$latest" | sort -t $'\t' -k1,1nr | head -1
    )

    echo "Candidato selecionado de: $latest"
    awk -v b="$bytes" -v s="$SCHEMA" -v t="$TABLE" -v r="$rows" \
        'BEGIN {printf "  %s.%s  %.2f GiB  rows_audit=%s\n", s,t,b/1024/1024/1024,r}'
fi

[[ "$SCHEMA" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || exit 44
[[ "$TABLE" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || exit 44

target_dir="$LAKE_ROOT/bronze/legacy_psql/$SCHEMA"
mkdir -p "$target_dir" "$LAKE_ROOT/work/duckdb" "$LAKE_ROOT/state/psql" "$LAKE_ROOT/logs/psql"

output="$target_dir/$TABLE.parquet"
partial="$output.partial.$$"
rm -f "$partial"

echo
echo "Origem: $SCHEMA.$TABLE"
echo "Destino: $output"

read -r -p "Digite MIGRAR $SCHEMA.$TABLE para executar: " token
[[ "$token" == "MIGRAR $SCHEMA.$TABLE" ]] || {
    echo "Cancelado."
    exit 0
}

rows_psql="$(
    PGPASSWORD="$BURETA_DB_PASSWORD" psql \
        -h "$BURETA_HOST" -p "$BURETA_DB_PORT" \
        -U "$BURETA_DB_USER" -d "$BURETA_DB_NAME" \
        -Atq -v ON_ERROR_STOP=1 \
        -c "SELECT count(*)::bigint FROM \"$SCHEMA\".\"$TABLE\";"
)"

urlencode() {
    local LC_ALL=C s="$1" out="" c i hex
    for ((i=0; i<${#s}; i++)); do
        c="${s:i:1}"
        case "$c" in
            [a-zA-Z0-9.~_-]) out+="$c" ;;
            *) printf -v hex '%%%02X' "'$c"; out+="$hex" ;;
        esac
    done
    printf '%s' "$out"
}

uri="postgresql://$(urlencode "$BURETA_DB_USER"):$(urlencode "$BURETA_DB_PASSWORD")@${BURETA_HOST}:${BURETA_DB_PORT}/$(urlencode "$BURETA_DB_NAME")"

if ! duckdb -c "LOAD postgres;" >/dev/null 2>&1; then
    duckdb -c "INSTALL postgres; LOAD postgres;" >/dev/null
fi

duckdb -c "
    LOAD postgres;
    SET temp_directory='$LAKE_ROOT/work/duckdb';
    SET preserve_insertion_order=false;
    ATTACH '$uri' AS src (TYPE POSTGRES, READ_ONLY);
    COPY (
        SELECT *
        FROM src.\"$SCHEMA\".\"$TABLE\"
    )
    TO '$partial'
    (FORMAT PARQUET, COMPRESSION ZSTD);
"

rows_parquet="$(duckdb -csv -noheader -c "SELECT count(*) FROM read_parquet('$partial');" | tr -d '\r')"

if [[ "$rows_psql" != "$rows_parquet" ]]; then
    echo "ERRO QC: psql=$rows_psql parquet=$rows_parquet" >&2
    exit 45
fi

mv -f "$partial" "$output"

bytes="$(stat -c '%s' "$output")"
printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(date -Is)" "$SCHEMA" "$TABLE" "$rows_psql" "$bytes" "$output" \
    >> "$LAKE_ROOT/state/psql/migrations.tsv"

echo "QC OK: rows=$rows_psql"
du -h "$output"

if (( DROP == 1 )); then
    echo
    read -r -p "Digite DROP $SCHEMA.$TABLE para excluir a tabela PostgreSQL: " token
    if [[ "$token" == "DROP $SCHEMA.$TABLE" ]]; then
        PGPASSWORD="$BURETA_DB_PASSWORD" psql \
            -h "$BURETA_HOST" -p "$BURETA_DB_PORT" \
            -U "$BURETA_DB_USER" -d "$BURETA_DB_NAME" \
            -v ON_ERROR_STOP=1 \
            -c "DROP TABLE \"$SCHEMA\".\"$TABLE\";"
        echo "DROP concluido: $SCHEMA.$TABLE"
        df -h /var
    else
        echo "DROP cancelado; Parquet permanece publicado."
    fi
fi
