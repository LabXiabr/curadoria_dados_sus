#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-pipeta}"
UF="${2:-AC}"
COMP="${3:-202604}"

SIGTAP="/dados/abertos/suslake/silver/sigtap"
OUTDIR="/tmp/suslake_pa_sigtap_${UF}_${COMP}"
mkdir -p "$OUTDIR"

PSQL=(psql "service=$SERVICE" -X -v ON_ERROR_STOP=1)

LIST="$("${PSQL[@]}" -Atq -c "
SELECT table_schema||'.'||table_name
FROM information_schema.tables
WHERE table_schema='public'
  AND table_name ~ '^lista_dissemin_dbc_[0-9]{8}$'
ORDER BY table_name DESC
LIMIT 1;
")"

PA="$("${PSQL[@]}" -Atq -F '|' -c "
SELECT no_schema, no_tabela
FROM $LIST
WHERE upper(sg_sistema)='SIA'
  AND upper(sg_subsistema)='PA'
  AND upper(sg_uf)=upper('$UF')
  AND nu_competencia=$COMP
  AND coalesce(st_existe_sql,0)=1
LIMIT 1;
")"

if [[ -z "$PA" ]]; then
    echo "ERRO: SIA/PA não encontrado para $UF/$COMP" >&2
    exit 1
fi


logical_relation_sql() {
    local sistema="$1"
    local subsistema="$2"
    local lista
    local tables=()

    lista="$(psql "service=$SERVICE" -X -Atq -c "
        SELECT table_schema||'.'||table_name
        FROM information_schema.tables
        WHERE table_schema='public'
          AND table_name ~ '^lista_dissemin_dbc_[0-9]{8}$'
        ORDER BY table_name DESC
        LIMIT 1;
    ")"

    mapfile -t tables < <(
        psql "service=$SERVICE" -X -Atq -c "
        SELECT format('%I.%I', no_schema, no_tabela)
        FROM $lista
        WHERE sg_sistema='${sistema}'
          AND sg_subsistema='${subsistema}'
          AND sg_uf='${UF}'
          AND nu_competencia=${COMP}
          AND coalesce(st_existe_sql,0)=1
        ORDER BY no_tabela;
        "
    )

    ((${#tables[@]} > 0)) || return 1

    printf '('
    local sep=''
    local t
    for t in "${tables[@]}"; do
        printf '%sSELECT * FROM %s' "$sep" "$t"
        sep=' UNION ALL '
    done
    printf ')'
}

IFS='|' read -r PA_SCHEMA PA_TABLE <<< "$PA"
PA_REL="$(logical_relation_sql SIA PA)"
PA_PARTS=$(grep -o 'SELECT \* FROM' <<< "$PA_REL" | wc -l)
echo "PA logical parts=$PA_PARTS" >&2

echo "service=$SERVICE"
echo "UF=$UF"
echo "competencia=$COMP"
echo "PA=$PA_SCHEMA.$PA_TABLE"
echo

# ----------------------------------------------------------
# SIGTAP temporal válido na competência
# ----------------------------------------------------------

duckdb -c "
COPY (
    WITH
    r AS (
        SELECT
            co_procedimento,
            co_registro
        FROM read_parquet(
          '$SIGTAP/rl_procedimento_registro/temporal.parquet'
        )
        WHERE valid_from_competencia <= '$COMP'
          AND (
              valid_to_competencia IS NULL
              OR valid_to_competencia >= '$COMP'
          )
    ),
    t AS (
        SELECT
            co_registro,
            no_registro
        FROM read_parquet(
          '$SIGTAP/tb_registro/temporal.parquet'
        )
        WHERE valid_from_competencia <= '$COMP'
          AND (
              valid_to_competencia IS NULL
              OR valid_to_competencia >= '$COMP'
          )
    )
    SELECT DISTINCT
        r.co_procedimento,
        r.co_registro,
        t.no_registro
    FROM r
    LEFT JOIN t USING (co_registro)
    ORDER BY r.co_procedimento, r.co_registro
)
TO '$OUTDIR/sigtap_procedimento_registro.tsv'
(
    HEADER,
    DELIMITER E'\t'
);
"

echo "=== INSTRUMENTOS SIGTAP ATIVOS ==="

duckdb -box -c "
SELECT
    co_registro,
    no_registro,
    count(DISTINCT co_procedimento) AS procedimentos
FROM read_csv(
    '$OUTDIR/sigtap_procedimento_registro.tsv',
    delim='\t',
    header=true,
    all_varchar=true
)
GROUP BY co_registro, no_registro
ORDER BY co_registro;
"

echo
echo "=== PA x SIGTAP ==="

"${PSQL[@]}" -P pager=off <<SQL

CREATE TEMP TABLE sigtap_registro (
    co_procedimento text,
    co_registro text,
    no_registro text
);

\copy sigtap_registro FROM '$OUTDIR/sigtap_procedimento_registro.tsv' WITH (FORMAT csv, HEADER true, DELIMITER E'\t');

-- --------------------------------------------------------
-- 1. Qualidade estrutural de PA_PROC_ID
-- --------------------------------------------------------

SELECT
    count(*) AS registros_pa,

    count(*) FILTER (
        WHERE pa_proc_id IS NULL
           OR (CASE
    WHEN btrim(pa_proc_id::text) ~ '^[0-9]{1,10}$'
    THEN lpad(btrim(pa_proc_id::text),10,'0')
    ELSE btrim(pa_proc_id::text)
END)=''
    ) AS proc_null,

    count(*) FILTER (
        WHERE (CASE
    WHEN btrim(pa_proc_id::text) ~ '^[0-9]{1,10}$'
    THEN lpad(btrim(pa_proc_id::text),10,'0')
    ELSE btrim(pa_proc_id::text)
END) ~ '^[0-9]{10}$'
    ) AS proc_10_digitos,

    count(*) FILTER (
        WHERE NOT (
            (CASE
    WHEN btrim(pa_proc_id::text) ~ '^[0-9]{1,10}$'
    THEN lpad(btrim(pa_proc_id::text),10,'0')
    ELSE btrim(pa_proc_id::text)
END) ~ '^[0-9]{10}$'
        )
    ) AS proc_formato_invalido

FROM $PA_REL;


-- --------------------------------------------------------
-- 2. Cobertura referencial por PA_DOCORIG
-- Não duplica registros quando procedimento possui
-- múltiplos instrumentos permitidos no SIGTAP.
-- --------------------------------------------------------

WITH
s AS (
    SELECT
        co_procedimento,
        count(DISTINCT co_registro) AS n_registros_sigtap
    FROM sigtap_registro
    GROUP BY co_procedimento
),
p AS (
    SELECT
        coalesce(nullif(btrim(pa_docorig::text),''),'<NULL>') AS pa_docorig,
        (CASE
    WHEN btrim(pa_proc_id::text) ~ '^[0-9]{1,10}$'
    THEN lpad(btrim(pa_proc_id::text),10,'0')
    ELSE btrim(pa_proc_id::text)
END) AS co_procedimento,
        count(*) AS registros
    FROM $PA_REL
    GROUP BY 1,2
)
SELECT
    p.pa_docorig,

    sum(p.registros) AS registros,

    count(*) AS procedimentos_observados,

    sum(p.registros) FILTER (
        WHERE s.co_procedimento IS NOT NULL
    ) AS registros_proc_encontrado,

    sum(p.registros) FILTER (
        WHERE s.co_procedimento IS NULL
    ) AS registros_proc_nao_encontrado,

    count(*) FILTER (
        WHERE s.co_procedimento IS NULL
    ) AS procedimentos_nao_encontrados,

    count(*) FILTER (
        WHERE s.n_registros_sigtap = 1
    ) AS procedimentos_um_instrumento,

    count(*) FILTER (
        WHERE s.n_registros_sigtap > 1
    ) AS procedimentos_multiplos_instrumentos

FROM p
LEFT JOIN s USING (co_procedimento)

GROUP BY p.pa_docorig
ORDER BY p.pa_docorig;


-- --------------------------------------------------------
-- 3. Matriz real:
-- PA_DOCORIG x conjunto de instrumentos permitidos
-- --------------------------------------------------------

WITH
s AS (
    SELECT
        co_procedimento,

        count(DISTINCT co_registro) AS n_registros,

        string_agg(
            DISTINCT
            co_registro || '=' || coalesce(no_registro,'<SEM NOME>'),
            ' | '
            ORDER BY
            co_registro || '=' || coalesce(no_registro,'<SEM NOME>')
        ) AS registros_permitidos

    FROM sigtap_registro
    GROUP BY co_procedimento
),
p AS (
    SELECT
        coalesce(nullif(btrim(pa_docorig::text),''),'<NULL>') AS pa_docorig,
        (CASE
    WHEN btrim(pa_proc_id::text) ~ '^[0-9]{1,10}$'
    THEN lpad(btrim(pa_proc_id::text),10,'0')
    ELSE btrim(pa_proc_id::text)
END) AS co_procedimento,
        count(*) AS registros
    FROM $PA_REL
    GROUP BY 1,2
)
SELECT
    p.pa_docorig,

    coalesce(
        s.registros_permitidos,
        '<PROCEDIMENTO AUSENTE NO SIGTAP>'
    ) AS registros_permitidos,

    count(*) AS procedimentos,

    sum(p.registros) AS registros_pa

FROM p
LEFT JOIN s USING (co_procedimento)

GROUP BY
    p.pa_docorig,
    s.registros_permitidos

ORDER BY
    p.pa_docorig,
    registros_pa DESC;


-- --------------------------------------------------------
-- 4. Procedimentos sem correspondência SIGTAP
-- --------------------------------------------------------

WITH
s AS (
    SELECT DISTINCT co_procedimento
    FROM sigtap_registro
)
SELECT
    pa_docorig,
    pa_proc_id,
    count(*) AS registros
FROM $PA_REL p

LEFT JOIN s
  ON s.co_procedimento=btrim(p.pa_proc_id::text)

WHERE s.co_procedimento IS NULL

GROUP BY
    pa_docorig,
    pa_proc_id

ORDER BY registros DESC
LIMIT 30;

SQL

echo
echo "SIGTAP exportado:"
echo "$OUTDIR/sigtap_procedimento_registro.tsv"
