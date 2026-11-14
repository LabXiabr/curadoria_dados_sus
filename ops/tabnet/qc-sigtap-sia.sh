#!/usr/bin/env bash
set -Eeuo pipefail

COMP="${1:?Uso: $0 YYYYMM TABNET_DIR}"
TABNET_DIR="${2:?Uso: $0 YYYYMM TABNET_DIR}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"

BRONZE="$LAKE_ROOT/bronze/sigtap"
STATE="$LAKE_ROOT/state/sigtap"

for c in duckdb awk sort; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 2
    }
done

ts="$(date +%Y%m%d_%H%M%S)"
out="$STATE/qc_tabnet_sia_static_${COMP}_${ts}.tsv"
hier="$STATE/qc_tabnet_sia_static_hierarchy_${COMP}_${ts}.tsv"

printf 'domain\ttabnet_count\tsigtap_count\tintersection\tonly_tabnet\tonly_sigtap\tstatus\n' > "$out"
printf 'rule\tcount\tstatus\n' > "$hier"

compare_domain() {
    local domain="$1"
    local table="$2"
    local code_sql="$3"
    local tab="$TABNET_DIR/${domain}.tsv"
    local pq="$BRONZE/$table/competencia=$COMP/part-000.parquet"

    [[ -f "$tab" && -f "$pq" ]] || return 0

    result="$(
      duckdb -csv -noheader -c "
        WITH
        t AS (
          SELECT DISTINCT codigo
          FROM read_csv('$tab', delim='	', header=true, all_varchar=true)
          WHERE codigo IS NOT NULL AND trim(codigo)<>''
        ),
        s AS (
          SELECT DISTINCT $code_sql AS codigo
          FROM read_parquet('$pq')
          WHERE $code_sql IS NOT NULL AND trim($code_sql)<>''
        )
        SELECT
          (SELECT count(*) FROM t),
          (SELECT count(*) FROM s),
          (SELECT count(*) FROM t INNER JOIN s USING(codigo)),
          (SELECT count(*) FROM (SELECT codigo FROM t EXCEPT SELECT codigo FROM s)),
          (SELECT count(*) FROM (SELECT codigo FROM s EXCEPT SELECT codigo FROM t));
      " | tr -d '\r'
    )"

    IFS=',' read -r nt ns ni ot os <<< "$result"

    if [[ "$ot" == "0" && "$os" == "0" ]]; then
        status="exact"
    else
        status="informative_temporal_difference"
    fi

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$domain" "$nt" "$ns" "$ni" "$ot" "$os" "$status" >> "$out"
}

compare_domain grupo tb_grupo "co_grupo"
compare_domain subgrupo tb_sub_grupo "co_grupo || co_sub_grupo"
compare_domain forma tb_forma_organizacao "co_grupo || co_sub_grupo || co_forma_organizacao"
compare_domain procedimento tb_procedimento "co_procedimento"

duckdb -csv -noheader -c "
  WITH
  g AS (SELECT codigo FROM read_csv('$TABNET_DIR/grupo.tsv', delim='	', header=true, all_varchar=true)),
  s AS (SELECT codigo FROM read_csv('$TABNET_DIR/subgrupo.tsv', delim='	', header=true, all_varchar=true)),
  f AS (SELECT codigo FROM read_csv('$TABNET_DIR/forma.tsv', delim='	', header=true, all_varchar=true)),
  p AS (SELECT codigo FROM read_csv('$TABNET_DIR/procedimento.tsv', delim='	', header=true, all_varchar=true))
  SELECT 'subgrupo_sem_grupo', count(*) FROM s LEFT JOIN g ON left(s.codigo,2)=g.codigo WHERE g.codigo IS NULL
  UNION ALL
  SELECT 'forma_sem_subgrupo', count(*) FROM f LEFT JOIN s ON left(f.codigo,4)=s.codigo WHERE s.codigo IS NULL
  UNION ALL
  SELECT 'procedimento_sem_forma', count(*) FROM p LEFT JOIN f ON left(p.codigo,6)=f.codigo WHERE f.codigo IS NULL
  UNION ALL
  SELECT 'procedimento_sem_subgrupo', count(*) FROM p LEFT JOIN s ON left(p.codigo,4)=s.codigo WHERE s.codigo IS NULL
  UNION ALL
  SELECT 'procedimento_sem_grupo', count(*) FROM p LEFT JOIN g ON left(p.codigo,2)=g.codigo WHERE g.codigo IS NULL;
" | tr -d '\r' | while IFS=',' read -r rule count; do
    [[ "$count" == "0" ]] && status="ok" || status="warning"
    printf '%s\t%s\t%s\n' "$rule" "$count" "$status"
done >> "$hier"

echo "=== Catalogo estatico TabNet x SIGTAP $COMP (INFORMATIVO) ==="
column -s $'\t' -t "$out" || cat "$out"
echo
echo "=== Coerencia interna do catalogo estatico TabNet ==="
column -s $'\t' -t "$hier" || cat "$hier"
echo
echo "hard_failures=0"
echo "note=O formulario TabNet preserva categorias historicas; nao e catalogo vigente por competencia."
echo "report=$out"
echo "hierarchy_report=$hier"
