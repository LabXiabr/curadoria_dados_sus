#!/usr/bin/env bash
set -Eeuo pipefail

COMP="${1:?Uso: $0 YYYYMM TABNET_TSV}"
TAB="${2:?Uso: $0 YYYYMM TABNET_TSV}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"

BRONZE="$LAKE_ROOT/bronze/sigtap"
STATE="$LAKE_ROOT/state/sigtap"
ts="$(date +%Y%m%d_%H%M%S)"

for c in duckdb awk; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 2
    }
done

p_proc="$BRONZE/tb_procedimento/competencia=$COMP/part-000.parquet"
p_grp="$BRONZE/tb_grupo/competencia=$COMP/part-000.parquet"
p_sub="$BRONZE/tb_sub_grupo/competencia=$COMP/part-000.parquet"
p_for="$BRONZE/tb_forma_organizacao/competencia=$COMP/part-000.parquet"

for f in "$TAB" "$p_proc" "$p_grp" "$p_sub" "$p_for"; do
    [[ -f "$f" ]] || {
        echo "ERRO: arquivo ausente: $f" >&2
        exit 3
    }
done

out="$STATE/qc_tabnet_sia_monthly_${COMP}_${ts}.tsv"
printf 'rule\tcount\tstatus\n' > "$out"

result="$(
duckdb -csv -noheader -c "
WITH
t AS (
  SELECT DISTINCT codigo
  FROM read_csv('$TAB', delim='	', header=true, all_varchar=true)
),
p AS (
  SELECT DISTINCT co_procedimento AS codigo
  FROM read_parquet('$p_proc')
),
g AS (
  SELECT DISTINCT co_grupo AS codigo
  FROM read_parquet('$p_grp')
),
s AS (
  SELECT DISTINCT co_grupo || co_sub_grupo AS codigo
  FROM read_parquet('$p_sub')
),
f AS (
  SELECT DISTINCT co_grupo || co_sub_grupo || co_forma_organizacao AS codigo
  FROM read_parquet('$p_for')
)
SELECT 'tabnet_procedimentos', count(*) FROM t
UNION ALL
SELECT 'sigtap_procedimentos', count(*) FROM p
UNION ALL
SELECT 'tabnet_procedimento_ausente_sigtap', count(*) FROM (SELECT codigo FROM t EXCEPT SELECT codigo FROM p)
UNION ALL
SELECT 'tabnet_procedimento_sem_grupo_sigtap', count(*) FROM t LEFT JOIN g ON left(t.codigo,2)=g.codigo WHERE g.codigo IS NULL
UNION ALL
SELECT 'tabnet_procedimento_sem_subgrupo_sigtap', count(*) FROM t LEFT JOIN s ON left(t.codigo,4)=s.codigo WHERE s.codigo IS NULL
UNION ALL
SELECT 'tabnet_procedimento_sem_forma_sigtap', count(*) FROM t LEFT JOIN f ON left(t.codigo,6)=f.codigo WHERE f.codigo IS NULL;
" | tr -d '\r'
)"

while IFS=',' read -r rule count; do
    case "$rule" in
        tabnet_procedimentos|sigtap_procedimentos)
            status="info"
            ;;
        *)
            [[ "$count" == "0" ]] && status="ok" || status="error"
            ;;
    esac
    printf '%s\t%s\t%s\n' "$rule" "$count" "$status" >> "$out"
done <<< "$result"

echo "=== TabNet mensal x SIGTAP $COMP ==="
column -s $'\t' -t "$out" || cat "$out"

hard="$(awk -F'\t' 'NR>1 && $3=="error"{n++} END{print n+0}' "$out")"
echo
echo "hard_failures=$hard"
echo "report=$out"

if (( hard == 0 )); then
    marker="$STATE/qc_tabnet_sia_monthly_${COMP}.ok"
    {
        echo "competencia=$COMP"
        echo "timestamp=$(date -Is)"
        echo "tabnet_file=$TAB"
        echo "report=$out"
        echo "rule=procedures_with_observed_sia_production_must_exist_in_same_competence_sigtap"
    } > "$marker"
    echo "TABNET_MONTHLY_QC_OK $marker"
else
    exit 20
fi
