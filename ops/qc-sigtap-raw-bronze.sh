#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
COMP="${1:-202502}"

RAW="$LAKE_ROOT/raw/sigtap/zip"
BRONZE="$LAKE_ROOT/bronze/sigtap"
STATE="$LAKE_ROOT/state/sigtap"
WORKROOT="$LAKE_ROOT/work/sigtap_qc"

for c in unzip python3 duckdb sha256sum sort awk sed; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 2
    }
done

zip="$(
    find "$RAW" -maxdepth 1 -type f -name "TabelaUnificada_${COMP}_*.zip" -printf '%p\n' \
    | sort | tail -1
)"
[[ -n "$zip" ]] || {
    echo "ERRO: ZIP nao encontrado para $COMP" >&2
    exit 3
}

ts="$(date +%Y%m%d_%H%M%S)"
work="$WORKROOT/${COMP}_${ts}"
mkdir -p "$work/extract" "$STATE"
trap 'rm -rf "$work"' EXIT

unzip -q "$zip" -d "$work/extract"

out="$STATE/qc_raw_bronze_${COMP}_${ts}.tsv"
printf 'table\trows_raw\trows_parquet\thash_raw\thash_parquet\tstatus\n' > "$out"

fail=0
n=0

while IFS= read -r -d '' txt; do
    base="$(basename "$txt")"
    table="$(printf '%s' "${base%.*}" | tr '[:upper:]' '[:lower:]')"

    case "$table" in
        layout|leia_me|*_layout) continue ;;
    esac

    lf="$(find "$work/extract" -type f -iname "${table}_layout.txt" -print -quit)"
    pq="$BRONZE/$table/competencia=$COMP/part-000.parquet"

    [[ -n "$lf" ]] || {
        printf '%s\t\t\t\t\tmissing_layout\n' "$table" >> "$out"
        ((fail+=1))
        continue
    }
    [[ -f "$pq" ]] || {
        printf '%s\t\t\t\t\tmissing_parquet\n' "$table" >> "$out"
        ((fail+=1))
        continue
    }

    raw_hashes="$work/${table}.raw.hashes"
    pq_hashes="$work/${table}.pq.hashes"

    rows_raw="$(
        python3 - "$txt" "$lf" "$raw_hashes" <<'PY'
import csv, hashlib, sys

txt, layout, out = sys.argv[1:4]

cols = []
with open(layout, "r", encoding="latin-1", newline="") as f:
    for row in csv.DictReader(f):
        cols.append((int(row["Inicio"]), int(row["Fim"])))

hashes = []
rows = 0

with open(txt, "rb") as f:
    for line in f:
        line = line.rstrip(b"\r\n")
        vals = []
        for start, end in cols:
            b = line[start-1:end].strip(b" ")
            vals.append(b.decode("latin-1"))
        canonical = "".join(f"{len(v)}:{v}\x1f" for v in vals)
        hashes.append(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        rows += 1

hashes.sort()
with open(out, "w", encoding="ascii") as g:
    for h in hashes:
        g.write(h + "\n")

print(rows)
PY
    )"

    fields="$(
        awk -F',' 'NR>1 {gsub(/\r/,""); printf "%s%s",tolower($1),(NR==n?"":"|")}' \
            n="$(wc -l < "$lf")" "$lf"
    )"

    IFS='|' read -r -a cols <<< "$fields"
    expr="concat("
    first=1
    for field in "${cols[@]}"; do
        q="\"$field\""
        v="coalesce(cast($q as varchar),'')"
        part="cast(length($v) as varchar), ':', $v, chr(31)"
        if (( first == 0 )); then
            expr+=", "
        fi
        expr+="$part"
        first=0
    done
    expr+=")"

    duckdb -csv -noheader -c "
        SELECT sha256($expr) AS h
        FROM read_parquet('$pq')
        ORDER BY h;
    " | tr -d '\r' > "$pq_hashes"

    rows_parquet="$(wc -l < "$pq_hashes")"
    hash_raw="$(sha256sum "$raw_hashes" | awk '{print $1}')"
    hash_parquet="$(sha256sum "$pq_hashes" | awk '{print $1}')"

    if [[ "$rows_raw" == "$rows_parquet" && "$hash_raw" == "$hash_parquet" ]]; then
        status="ok"
    else
        status="mismatch"
        ((fail+=1))
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$table" "$rows_raw" "$rows_parquet" "$hash_raw" "$hash_parquet" "$status" >> "$out"
    ((n+=1))
done < <(find "$work/extract" -type f -iname '*.txt' -print0 | sort -z)

echo "Relatorio: $out"
awk -F'\t' 'NR==1 || $6!="ok"' "$out" | column -s $'\t' -t || true
echo "Tabelas: $n"
echo "Falhas: $fail"

if (( fail == 0 && n > 0 )); then
    marker="$STATE/qc_raw_bronze_${COMP}.ok"
    {
        echo "competencia=$COMP"
        echo "timestamp=$(date -Is)"
        echo "zip=$(basename "$zip")"
        echo "zip_sha256=$(sha256sum "$zip" | awk '{print $1}')"
        echo "tables=$n"
        echo "method=independent_python_fixed_width_vs_parquet_row_hash"
        echo "report=$out"
    } > "$marker"
    echo "RAW_BRONZE_QC_OK $marker"
else
    exit 20
fi
