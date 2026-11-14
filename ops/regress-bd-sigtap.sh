#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
COMP="${1:-202502}"
OLD_REPO="${OLD_REPO:-https://github.com/LabXiabr/bd_sigtap.git}"

BRONZE="$LAKE_ROOT/bronze/sigtap"
STATE="$LAKE_ROOT/state/sigtap"

command -v git >/dev/null
command -v duckdb >/dev/null

mkdir -p "$STATE"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --quiet --depth 1 "$OLD_REPO" "$tmp/bd_sigtap"

ts="$(date +%Y%m%d_%H%M%S)"
out="$STATE/regression_bd_sigtap_${COMP}_${ts}.tsv"
printf 'table\trows_legacy\trows_parquet\tstatus\n' > "$out"

fail=0
n=0

shopt -s nullglob
for csv in "$tmp"/bd_sigtap/*.csv; do
    table="$(basename "$csv" .csv)"
    pq="$BRONZE/$table/competencia=$COMP/part-000.parquet"

    legacy_rows="$(
        awk 'END {print (NR>0 ? NR-1 : 0)}' "$csv"
    )"

    if [[ ! -f "$pq" ]]; then
        printf '%s\t%s\t\tmissing_parquet\n' "$table" "$legacy_rows" >> "$out"
        ((fail+=1))
        continue
    fi

    parquet_rows="$(duckdb -csv -noheader -c "SELECT count(*) FROM read_parquet('$pq');" | tr -d '\r')"

    if [[ "$legacy_rows" == "$parquet_rows" ]]; then
        status="ok"
    else
        status="row_mismatch"
        ((fail+=1))
    fi

    printf '%s\t%s\t%s\t%s\n' "$table" "$legacy_rows" "$parquet_rows" "$status" >> "$out"
    ((n+=1))
done

echo "Relatorio: $out"
awk -F'\t' 'NR==1 || $4!="ok"' "$out" | column -s $'\t' -t || true
echo "Tabelas comparadas: $n"
echo "Falhas: $fail"

if (( fail == 0 && n > 0 )); then
    marker="$STATE/regression_bd_sigtap_${COMP}.ok"
    {
        echo "competencia=$COMP"
        echo "timestamp=$(date -Is)"
        echo "legacy_repo=$OLD_REPO"
        echo "tables=$n"
    } > "$marker"
    echo "REGRESSION_OK $marker"
else
    exit 20
fi
