#!/usr/bin/env bash
set -Eeuo pipefail

BASE="${SIGTAP_HTTPS_BASE:-https://dados.labx.ia.br/files/suslabx/bronze/sigtap/tb_procedimento/}"

for c in curl sed sort duckdb mktemp; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 2
    }
done

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

curl -fsS "$BASE"     | sed -nE 's/.*href="competencia=([0-9]{6})\/".*/\1/p'     | sort -u > "$tmp"

n="$(wc -l < "$tmp")"
(( n > 0 )) || {
    echo "ERRO: nenhuma competencia descoberta em $BASE" >&2
    exit 3
}

urls=""
while IFS= read -r comp; do
    url="${BASE}competencia=${comp}/part-000.parquet"
    if [[ -n "$urls" ]]; then urls+=", "; fi
    urls+="'${url}'"
done < "$tmp"

echo "Competencias descobertas: $n" >&2

duckdb -c "
INSTALL httpfs;
LOAD httpfs;
SELECT
    _source_competencia AS competencia,
    count(*) AS registros
FROM read_parquet(
    [$urls],
    union_by_name=true,
    hive_partitioning=true
)
GROUP BY 1
ORDER BY 1;
"
