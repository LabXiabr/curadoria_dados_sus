#!/usr/bin/env bash
set -euo pipefail

SERVICE="${1:-pipeta}"
UF="${2:-AC}"
COMP="${3:-202604}"

OUTDIR="/tmp/suslake_fact_qc_${UF}_${COMP}"
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

echo "service=$SERVICE uf=$UF competencia=$COMP lista=$LIST" >&2

get_table() {
    local system="$1" subsystem="$2"

    "${PSQL[@]}" -Atq -F'|' -c "
    SELECT no_schema, no_tabela
    FROM $LIST
    WHERE upper(sg_sistema)=upper('$system')
      AND upper(sg_subsistema)=upper('$subsystem')
      AND upper(sg_uf)=upper('$UF')
      AND nu_competencia=$COMP
      AND coalesce(st_existe_sql,0)=1
    ORDER BY no_tabela
    LIMIT 1;
    "
}

has_column() {
    local schema="$1" table="$2" col="$3"

    "${PSQL[@]}" -Atq -c "
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='$schema'
          AND table_name='$table'
          AND column_name='$col'
    )::int;
    "
}

CARD="$OUTDIR/cardinality.tsv"
CNES="$OUTDIR/cnes_consistency.tsv"

printf 'system\tparent\tchild\tparent_rows_with_key\tparent_keys\tparent_keys_multi\tparent_max_rows_per_key\tchild_rows_with_key\tchild_keys\tchild_keys_multi\tchild_max_rows_per_key\tmatched_keys\tunmatched_child_keys\tmatched_child_rows\tunmatched_child_rows\tmany_to_many_keys\n' > "$CARD"

printf 'system\tparent\tchild\tmatched_keys\tparent_cnes_unique\tchild_cnes_unique\tsame_cnes\tdifferent_cnes\tambiguous_cnes\n' > "$CNES"

# ----------------------------------------------------------
# SIA: PA <- APACs especializadas
# ----------------------------------------------------------


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

PA="$(get_table SIA PA)"

if [[ -z "$PA" ]]; then
    echo "ERRO: SIA/PA não encontrado para $UF/$COMP" >&2
    exit 1
fi

IFS='|' read -r PA_SCHEMA PA_TABLE <<< "$PA"
PA_REL="$(logical_relation_sql SIA PA)"
PA_PARTS=$(grep -o 'SELECT \* FROM' <<< "$PA_REL" | wc -l)
echo "PA logical parts=$PA_PARTS" >&2

echo "SIA PA = $PA_SCHEMA.$PA_TABLE" >&2

for SUB in AB ACF AD AM AMP AN AQ AR ATD
do
    CHILD="$(get_table SIA "$SUB")"
    [[ -z "$CHILD" ]] && continue

    IFS='|' read -r CS CT <<< "$CHILD"

    if [[ "$SUB" == "BI" ]]; then
        AUTH="autoriz"
        CCNES="coduni"
    else
        AUTH="ap_autoriz"
        CCNES="ap_coduni"
    fi

    [[ "$(has_column "$CS" "$CT" "$AUTH")" == "1" ]] || {
        echo "SIA/$SUB sem $AUTH: $CS.$CT" >&2
        continue
    }

    echo "QC SIA PA <- $SUB : $CS.$CT" >&2

    "${PSQL[@]}" -At -F $'\t' -c "
WITH
p AS (
    SELECT btrim(pa_autoriz::text) AS k,
           count(*)::bigint AS n
    FROM $PA_REL
    WHERE nullif(btrim(pa_autoriz::text),'') IS NOT NULL
      AND pa_docorig IN ('P','S')
      AND btrim(pa_autoriz::text) <> '0000000000000'
    GROUP BY 1
),
c AS (
    SELECT btrim(\"$AUTH\"::text) AS k,
           count(*)::bigint AS n
    FROM \"$CS\".\"$CT\"
    WHERE nullif(btrim(\"$AUTH\"::text),'') IS NOT NULL
    GROUP BY 1
),
j AS (
    SELECT c.k,
           c.n AS child_n,
           p.n AS parent_n
    FROM c
    LEFT JOIN p USING (k)
)
SELECT
    'SIA',
    'PA',
    '$SUB',
    (SELECT coalesce(sum(n),0) FROM p),
    (SELECT count(*) FROM p),
    (SELECT count(*) FROM p WHERE n>1),
    (SELECT coalesce(max(n),0) FROM p),
    (SELECT coalesce(sum(n),0) FROM c),
    (SELECT count(*) FROM c),
    (SELECT count(*) FROM c WHERE n>1),
    (SELECT coalesce(max(n),0) FROM c),
    count(*) FILTER (WHERE parent_n IS NOT NULL),
    count(*) FILTER (WHERE parent_n IS NULL),
    coalesce(sum(child_n) FILTER (WHERE parent_n IS NOT NULL),0),
    coalesce(sum(child_n) FILTER (WHERE parent_n IS NULL),0),
    count(*) FILTER (WHERE parent_n>1 AND child_n>1)
FROM j;
" >> "$CARD"

    if [[ "$(has_column "$CS" "$CT" "$CCNES")" == "1" ]]; then

        "${PSQL[@]}" -At -F $'\t' -c "
WITH
p AS (
    SELECT
        btrim(pa_autoriz::text) AS k,
        count(DISTINCT nullif(btrim(pa_coduni::text),'')) AS ncnes,
        min(nullif(btrim(pa_coduni::text),'')) AS cnes
    FROM $PA_REL
    WHERE nullif(btrim(pa_autoriz::text),'') IS NOT NULL
      AND pa_docorig IN ('P','S')
      AND btrim(pa_autoriz::text) <> '0000000000000'
    GROUP BY 1
),
c AS (
    SELECT
        btrim(\"$AUTH\"::text) AS k,
        count(DISTINCT nullif(btrim(\"$CCNES\"::text),'')) AS ncnes,
        min(nullif(btrim(\"$CCNES\"::text),'')) AS cnes
    FROM \"$CS\".\"$CT\"
    WHERE nullif(btrim(\"$AUTH\"::text),'') IS NOT NULL
    GROUP BY 1
),
j AS (
    SELECT
        p.k,
        p.ncnes AS p_n,
        p.cnes  AS p_cnes,
        c.ncnes AS c_n,
        c.cnes  AS c_cnes
    FROM p
    JOIN c USING (k)
)
SELECT
    'SIA',
    'PA',
    '$SUB',
    count(*),
    count(*) FILTER (WHERE p_n=1),
    count(*) FILTER (WHERE c_n=1),
    count(*) FILTER (
        WHERE p_n=1 AND c_n=1
          AND p_cnes IS NOT DISTINCT FROM c_cnes
    ),
    count(*) FILTER (
        WHERE p_n=1 AND c_n=1
          AND p_cnes IS DISTINCT FROM c_cnes
    ),
    count(*) FILTER (WHERE p_n<>1 OR c_n<>1)
FROM j;
" >> "$CNES"
    fi
done

# ----------------------------------------------------------
# SIH: RD <- SP
# ----------------------------------------------------------

RD="$(get_table SIH RD)"
SP="$(get_table SIH SP)"

if [[ -n "$RD" && -n "$SP" ]]; then

    IFS='|' read -r RD_SCHEMA RD_TABLE <<< "$RD"
    IFS='|' read -r SP_SCHEMA SP_TABLE <<< "$SP"

    echo "QC SIH RD <- SP" >&2
    echo "RD=$RD_SCHEMA.$RD_TABLE SP=$SP_SCHEMA.$SP_TABLE" >&2

    "${PSQL[@]}" -At -F $'\t' -c "
WITH
p AS (
    SELECT btrim(n_aih::text) AS k,
           count(*)::bigint AS n
    FROM \"$RD_SCHEMA\".\"$RD_TABLE\"
    WHERE nullif(btrim(n_aih::text),'') IS NOT NULL
    GROUP BY 1
),
c AS (
    SELECT btrim(sp_naih::text) AS k,
           count(*)::bigint AS n
    FROM \"$SP_SCHEMA\".\"$SP_TABLE\"
    WHERE nullif(btrim(sp_naih::text),'') IS NOT NULL
    GROUP BY 1
),
j AS (
    SELECT c.k,
           c.n AS child_n,
           p.n AS parent_n
    FROM c
    LEFT JOIN p USING (k)
)
SELECT
    'SIH',
    'RD',
    'SP',
    (SELECT coalesce(sum(n),0) FROM p),
    (SELECT count(*) FROM p),
    (SELECT count(*) FROM p WHERE n>1),
    (SELECT coalesce(max(n),0) FROM p),
    (SELECT coalesce(sum(n),0) FROM c),
    (SELECT count(*) FROM c),
    (SELECT count(*) FROM c WHERE n>1),
    (SELECT coalesce(max(n),0) FROM c),
    count(*) FILTER (WHERE parent_n IS NOT NULL),
    count(*) FILTER (WHERE parent_n IS NULL),
    coalesce(sum(child_n) FILTER (WHERE parent_n IS NOT NULL),0),
    coalesce(sum(child_n) FILTER (WHERE parent_n IS NULL),0),
    count(*) FILTER (WHERE parent_n>1 AND child_n>1)
FROM j;
" >> "$CARD"

    "${PSQL[@]}" -At -F $'\t' -c "
WITH
p AS (
    SELECT
        btrim(n_aih::text) AS k,
        count(DISTINCT nullif(btrim(cnes::text),'')) AS ncnes,
        min(nullif(btrim(cnes::text),'')) AS cnes
    FROM \"$RD_SCHEMA\".\"$RD_TABLE\"
    WHERE nullif(btrim(n_aih::text),'') IS NOT NULL
    GROUP BY 1
),
c AS (
    SELECT
        btrim(sp_naih::text) AS k,
        count(DISTINCT nullif(btrim(sp_cnes::text),'')) AS ncnes,
        min(nullif(btrim(sp_cnes::text),'')) AS cnes
    FROM \"$SP_SCHEMA\".\"$SP_TABLE\"
    WHERE nullif(btrim(sp_naih::text),'') IS NOT NULL
    GROUP BY 1
),
j AS (
    SELECT
        p.k,
        p.ncnes AS p_n,
        p.cnes  AS p_cnes,
        c.ncnes AS c_n,
        c.cnes  AS c_cnes
    FROM p
    JOIN c USING (k)
)
SELECT
    'SIH',
    'RD',
    'SP',
    count(*),
    count(*) FILTER (WHERE p_n=1),
    count(*) FILTER (WHERE c_n=1),
    count(*) FILTER (
        WHERE p_n=1 AND c_n=1
          AND p_cnes IS NOT DISTINCT FROM c_cnes
    ),
    count(*) FILTER (
        WHERE p_n=1 AND c_n=1
          AND p_cnes IS DISTINCT FROM c_cnes
    ),
    count(*) FILTER (WHERE p_n<>1 OR c_n<>1)
FROM j;
" >> "$CNES"

fi

echo
echo "=== CARDINALIDADE ==="
column -t -s $'\t' "$CARD"

echo
echo "=== CONSISTÊNCIA CNES ==="
column -t -s $'\t' "$CNES"

echo
echo "Arquivos:"
echo "$CARD"
echo "$CNES"
