#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAYOUT="$ROOT/systems/sigtap/layouts/fwf.tsv"

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
COMP="${1:-202502}"
OLD_REPO="${OLD_REPO:-https://github.com/LabXiabr/bd_sigtap.git}"

BRONZE="$LAKE_ROOT/bronze/sigtap"
STATE="$LAKE_ROOT/state/sigtap"

for c in git duckdb awk sed; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 2
    }
done

mkdir -p "$STATE"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --quiet --depth 1 "$OLD_REPO" "$tmp/bd_sigtap"

ts="$(date +%Y%m%d_%H%M%S)"
out="$STATE/regression_bd_sigtap_${COMP}_${ts}.tsv"

printf 'table\trows_legacy_physical\trows_legacy_valid\tblank_rows_ignored\trows_parquet\tlegacy_minus_parquet\tparquet_minus_legacy\tstatus\n' > "$out"

fail=0
n=0

quote_ident() {
    local x="$1"
    printf '"%s"' "${x//\"/\"\"}"
}

norm_expr() {
    local field="$1"
    local q
    q="$(quote_ident "$field")"

    case "$field" in
        qt_*|vl_*)
            printf '%s' \
              "CASE
                 WHEN NULLIF(TRIM(CAST($q AS VARCHAR)), '') IS NULL THEN NULL
                 WHEN TRY_CAST(TRIM(CAST($q AS VARCHAR)) AS DECIMAL(38,10)) IS NOT NULL
                   THEN CAST(TRY_CAST(TRIM(CAST($q AS VARCHAR)) AS DECIMAL(38,10)) AS VARCHAR)
                 ELSE TRIM(CAST($q AS VARCHAR))
               END AS $q"
            ;;
        *)
            printf '%s' "NULLIF(TRIM(CAST($q AS VARCHAR)), '') AS $q"
            ;;
    esac
}

nonblank_expr() {
    local field="$1"
    local q
    q="$(quote_ident "$field")"
    printf '%s' "NULLIF(TRIM(CAST($q AS VARCHAR)), '') IS NOT NULL"
}

shopt -s nullglob
for csv in "$tmp"/bd_sigtap/*.csv; do
    table="$(basename "$csv" .csv)"
    pq="$BRONZE/$table/competencia=$COMP/part-000.parquet"

    physical="$(
        awk 'END {print (NR>0 ? NR-1 : 0)}' "$csv"
    )"

    if [[ ! -f "$pq" ]]; then
        printf '%s\t%s\t\t\t\t\t\tmissing_parquet\n' \
            "$table" "$physical" >> "$out"
        ((fail+=1))
        continue
    fi

    fields="$(
        awk -F'\t' -v t="$table" -v c="$COMP" '
            NR>1 && $1==t && c>=$2 && c<=$3 {print $5; exit}
        ' "$LAYOUT"
    )"

    if [[ -z "$fields" ]]; then
        printf '%s\t%s\t\t\t\t\t\tmissing_layout\n' \
            "$table" "$physical" >> "$out"
        ((fail+=1))
        continue
    fi

    parquet_rows="$(
        duckdb -csv -noheader -c \
            "SELECT count(*) FROM read_parquet('$pq');" |
        tr -d '\r'
    )"

    # CSV apenas com cabecalho: evita depender do sniffer.
    if [[ "$physical" == "0" ]]; then
        legacy_valid=0
        blank_rows=0
        legacy_minus=0
        parquet_minus="$parquet_rows"
        if [[ "$parquet_rows" == "0" ]]; then
            status="ok"
        else
            status="content_mismatch"
            ((fail+=1))
        fi
    else
        IFS='|' read -r -a cols <<< "$fields"

        select_list=""
        nonblank=""

        for field in "${cols[@]}"; do
            ne="$(norm_expr "$field")"
            nb="$(nonblank_expr "$field")"

            if [[ -n "$select_list" ]]; then
                select_list+=", "
                nonblank+=" OR "
            fi

            select_list+="$ne"
            nonblank+="$nb"
        done

        result="$(
            duckdb -csv -noheader -c "
                WITH
                legacy AS (
                    SELECT $select_list
                    FROM read_csv(
                        '$csv',
                        header=true,
                        all_varchar=true,
                        null_padding=true
                    )
                    WHERE $nonblank
                ),
                bronze AS (
                    SELECT $select_list
                    FROM read_parquet('$pq')
                    WHERE $nonblank
                )
                SELECT
                    (SELECT count(*) FROM legacy),
                    (SELECT count(*) FROM (
                        SELECT * FROM legacy
                        EXCEPT ALL
                        SELECT * FROM bronze
                    ) x),
                    (SELECT count(*) FROM (
                        SELECT * FROM bronze
                        EXCEPT ALL
                        SELECT * FROM legacy
                    ) x);
            " | tr -d '\r'
        )"

        IFS=',' read -r legacy_valid legacy_minus parquet_minus <<< "$result"
        blank_rows=$(( physical - legacy_valid ))

        if [[ "$legacy_valid" == "$parquet_rows" &&
              "$legacy_minus" == "0" &&
              "$parquet_minus" == "0" ]]; then
            status="ok"
        else
            status="content_mismatch"
            ((fail+=1))
        fi
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$table" \
        "$physical" \
        "$legacy_valid" \
        "$blank_rows" \
        "$parquet_rows" \
        "$legacy_minus" \
        "$parquet_minus" \
        "$status" >> "$out"

    ((n+=1))
done

echo "Relatorio: $out"
echo

awk -F'\t' '
    NR==1 ||
    $4>0 ||
    $8!="ok"
' "$out" | column -s $'\t' -t || true

echo
echo "Tabelas comparadas: $n"
echo "Falhas: $fail"
echo "Linhas vazias ignoradas no legado: $(awk -F'\t' 'NR>1{s+=$4}END{print s+0}' "$out")"

if (( fail == 0 && n > 0 )); then
    marker="$STATE/regression_bd_sigtap_${COMP}.ok"
    {
        echo "competencia=$COMP"
        echo "timestamp=$(date -Is)"
        echo "legacy_repo=$OLD_REPO"
        echo "tables=$n"
        echo "comparison=count_and_normalized_content"
        echo "blank_legacy_rows_ignored=$(awk -F'\t' 'NR>1{s+=$4}END{print s+0}' "$out")"
        echo "report=$out"
    } > "$marker"

    echo
    echo "REGRESSION_OK $marker"
else
    exit 20
fi
