#!/usr/bin/env bash
set -uo pipefail

ROOT="${SUSLAKE_ROOT:-/dados/abertos/suslake}"
REPO="${REPO:-/dados/abertos/repos/curadoria_dados_sus}"

STATE="$ROOT/state/overnight"
STAGE="${SIH_STAGE:-$ROOT/staging/psql_snapshot/sih}"

# "SIH inteira" nesta rodada = família moderna 200801+
SIH_FROM="${SIH_FROM:-200801}"
SIH_TO="${SIH_TO:-202610}"

# 1 processo por servidor; cada DuckDB usa 2 threads
DUCK_THREADS="${DUCK_THREADS:-2}"

TS="$(date +%Y%m%d_%H%M%S)"
RUN="$STATE/$TS"

mkdir -p \
    "$RUN" \
    "$RUN/sia" \
    "$RUN/parquet_logs" \
    "$STAGE"

printf '%s\n' "$RUN" > "$STATE/LATEST"

exec > >(tee -a "$RUN/main.log") 2>&1

# impede duas rodadas simultâneas
exec 9>"$STATE/.overnight.lock"
if ! flock -n 9; then
    echo "ERRO: outra rodada overnight está ativa" >&2
    exit 2
fi

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $1" >&2
        exit 2
    }
}

for x in psql duckdb flock awk sed grep stat; do
    need "$x"
done


# ----------------------------------------------------------------------
# FUNÇÕES
# ----------------------------------------------------------------------

latest_list() {
    psql "service=$1" -X -Atq -v ON_ERROR_STOP=1 -c "
        SELECT table_schema||'.'||table_name
        FROM information_schema.tables
        WHERE table_schema='public'
          AND table_name ~ '^lista_dissemin_dbc_[0-9]{8}$'
        ORDER BY table_name DESC
        LIMIT 1;
    "
}

service_for_comp() {
    if (( 10#$1 < 202000 )); then
        printf 'bureta'
    else
        printf 'pipeta'
    fi
}

LIST_BURETA="$(latest_list bureta)"
LIST_PIPETA="$(latest_list pipeta)"

list_for_service() {
    if [[ "$1" == bureta ]]; then
        printf '%s' "$LIST_BURETA"
    else
        printf '%s' "$LIST_PIPETA"
    fi
}

logical_relation_sql() {
    local service="$1"
    local system="$2"
    local subsystem="$3"
    local uf="$4"
    local comp="$5"

    local lista
    lista="$(list_for_service "$service")"

    local tables=()

    mapfile -t tables < <(
        psql "service=$service" -X -Atq -v ON_ERROR_STOP=1 -c "
            SELECT format('%I.%I', no_schema, no_tabela)
            FROM $lista
            WHERE sg_sistema='$system'
              AND sg_subsistema='$subsystem'
              AND sg_uf='$uf'
              AND nu_competencia=$comp
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

append_tsv() {
    local file="$1"
    shift

    {
        flock 201
        printf '%s\n' "$*" >&201
    } 201>>"$file"
}


# ----------------------------------------------------------------------
# PREFLIGHT
# ----------------------------------------------------------------------

echo "=== PREFLIGHT ==="
echo "run=$RUN"
echo "stage=$STAGE"
echo "bureta_list=$LIST_BURETA"
echo "pipeta_list=$LIST_PIPETA"

df -h "$ROOT" || true

psql service=bureta -X -Atq -v ON_ERROR_STOP=1 \
    -c 'select current_database()' >/dev/null

psql service=pipeta -X -Atq -v ON_ERROR_STOP=1 \
    -c 'select current_database()' >/dev/null

# instala a extensão apenas se ainda não estiver disponível
if ! duckdb -c "LOAD postgres;" >/dev/null 2>&1; then
    duckdb -c "
        INSTALL postgres;
        LOAD postgres;
    " >/dev/null
fi

for svc in bureta pipeta; do
    duckdb -c "
        LOAD postgres;
        ATTACH 'service=$svc'
            AS pg
            (TYPE postgres, READ_ONLY);
        SELECT 1;
        DETACH pg;
    " >/dev/null

    echo "duckdb_postgres_ok=$svc"
done


# ======================================================================
# 1. QC SIH RD -> SP
#    TODOS OS 27 ESTADOS EM CINCO CORTES TEMPORAIS
# ======================================================================

QC_SIH="$RUN/qc_sih_rd_sp_segments.tsv"

printf \
'service\tuf\tcompetencia\tstatus\trd_rows\trd_aihs\trd_semantic_keys\trd_source_keys\trd_semantic_dup_keys\trd_source_dup_keys\tsp_rows\tsp_segments\tunmatched_sp_rows\trd_segments_without_sp\tdt_inter_diff\tcnes_diff\tsequencia_diff\tremessa_diff\n' \
> "$QC_SIH"

UFS=(
    AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB
    PR PE PI RJ RN RS RO RR SC SP SE TO
)

COMPS=(
    200801
    201204
    201603
    202001
    202604
)

echo "=== QC SIH RD-SP ==="

for comp in "${COMPS[@]}"; do

    svc="$(service_for_comp "$comp")"

    for uf in "${UFS[@]}"; do

        rd_rel="$(
            logical_relation_sql \
                "$svc" SIH RD "$uf" "$comp" \
                2>/dev/null || true
        )"

        sp_rel="$(
            logical_relation_sql \
                "$svc" SIH SP "$uf" "$comp" \
                2>/dev/null || true
        )"

        if [[ -z "$rd_rel" || -z "$sp_rel" ]]; then
            append_tsv "$QC_SIH" \
                "$svc"$'\t'"$uf"$'\t'"$comp"$'\t'MISSING
            continue
        fi

        sql="
WITH

r AS MATERIALIZED (
    SELECT
        btrim(n_aih::text) AS n_aih,
        btrim(dt_saida::text) AS dt_saida,
        btrim(dt_inter::text) AS dt_inter,
        btrim(cnes::text) AS cnes,
        btrim(sequencia::text) AS sequencia,
        btrim(remessa::text) AS remessa
    FROM $rd_rel q
),

s AS MATERIALIZED (
    SELECT
        btrim(sp_naih::text) AS n_aih,
        btrim(sp_dtsaida::text) AS dt_saida,
        btrim(sp_dtinter::text) AS dt_inter,
        btrim(sp_cnes::text) AS cnes,
        btrim(sequencia::text) AS sequencia,
        btrim(remessa::text) AS remessa
    FROM $sp_rel q
),

r1 AS MATERIALIZED (
    SELECT
        n_aih,
        dt_saida,
        min(dt_inter) AS dt_inter,
        min(cnes) AS cnes,
        min(sequencia) AS sequencia,
        min(remessa) AS remessa,
        count(*) AS n
    FROM r
    GROUP BY 1,2
),

rsource AS MATERIALIZED (
    SELECT
        remessa,
        sequencia,
        count(*) AS n
    FROM r
    GROUP BY 1,2
),

sk AS MATERIALIZED (
    SELECT DISTINCT
        n_aih,
        dt_saida
    FROM s
),

j AS MATERIALIZED (
    SELECT
        s.*,
        r1.n AS r_n,
        r1.dt_inter AS rd_dt_inter,
        r1.cnes AS rd_cnes,
        r1.sequencia AS rd_sequencia,
        r1.remessa AS rd_remessa
    FROM s
    LEFT JOIN r1
      USING (n_aih,dt_saida)
)

SELECT

    (SELECT count(*) FROM r),

    (SELECT count(DISTINCT n_aih) FROM r),

    (SELECT count(*) FROM r1),

    (SELECT count(*) FROM rsource),

    (SELECT count(*)
     FROM r1
     WHERE n > 1),

    (SELECT count(*)
     FROM rsource
     WHERE n > 1),

    (SELECT count(*) FROM s),

    (SELECT count(*) FROM sk),

    (SELECT count(*)
     FROM j
     WHERE r_n IS NULL),

    (SELECT count(*)
     FROM r1
     LEFT JOIN sk USING(n_aih,dt_saida)
     WHERE sk.n_aih IS NULL),

    (SELECT count(*)
     FROM j
     WHERE r_n=1
       AND dt_inter IS DISTINCT FROM rd_dt_inter),

    (SELECT count(*)
     FROM j
     WHERE r_n=1
       AND cnes IS DISTINCT FROM rd_cnes),

    (SELECT count(*)
     FROM j
     WHERE r_n=1
       AND sequencia IS DISTINCT FROM rd_sequencia),

    (SELECT count(*)
     FROM j
     WHERE r_n=1
       AND remessa IS DISTINCT FROM rd_remessa);
"

        if metrics="$(
            psql "service=$svc" \
                -X \
                -Atq \
                -F $'\t' \
                -v ON_ERROR_STOP=1 \
                -c "$sql" \
                2>"$RUN/qc_sih_${uf}_${comp}.err"
        )"
        then
            append_tsv "$QC_SIH" \
                "$svc"$'\t'"$uf"$'\t'"$comp"$'\t'OK$'\t'"$metrics"
        else
            append_tsv "$QC_SIH" \
                "$svc"$'\t'"$uf"$'\t'"$comp"$'\t'ERROR
        fi

    done

    echo "QC SIH concluído: $comp"
done


# ======================================================================
# 2. QC SIA
#    HISTÓRICO + UFs GRANDES/REGIONAIS
# ======================================================================

QC_SIA="$RUN/qc_sia_samples.tsv"

printf \
'service\tuf\tcompetencia\tsigtap_status\trelationship_status\n' \
> "$QC_SIA"

SAMPLES=(
    'AC 200801'
    'AC 201204'
    'AC 201603'
    'AC 202001'
    'AC 202604'

    'MG 201204'
    'MG 202604'

    'SP 202604'
    'BA 202604'
    'RS 202604'
    'AM 202604'
)

echo "=== QC SIA AMOSTRAL AMPLO ==="

for item in "${SAMPLES[@]}"; do

    read -r uf comp <<< "$item"

    svc="$(service_for_comp "$comp")"

    base="$RUN/sia/${svc}_${uf}_${comp}"

    s1=0
    s2=0

    "$REPO/ops/qc-sia-pa-sigtap.sh" \
        "$svc" "$uf" "$comp" \
        >"${base}_sigtap.log" 2>&1 \
        || s1=$?

    "$REPO/ops/qc-fact-relationships.sh" \
        "$svc" "$uf" "$comp" \
        >"${base}_relationships.log" 2>&1 \
        || s2=$?

    append_tsv "$QC_SIA" \
        "$svc"$'\t'"$uf"$'\t'"$comp"$'\t'"$s1"$'\t'"$s2"

    echo "QC SIA $uf/$comp status=$s1,$s2"
done


# ======================================================================
# 3. MANIFESTO CANÔNICO SIH
#    BURETA < 2020 ; PIPETA >= 2020
# ======================================================================

MANIFEST="$RUN/sih_manifest.tsv"

printf \
'service\tsubsystem\tuf\tcompetencia\tdbc\tschema\ttable\n' \
> "$MANIFEST"

for svc in bureta pipeta; do

    lista="$(list_for_service "$svc")"

    if [[ "$svc" == bureta ]]; then
        temporal="nu_competencia < 202000"
    else
        temporal="nu_competencia >= 202000"
    fi

    psql "service=$svc" \
        -X \
        -Atq \
        -F $'\t' \
        -v ON_ERROR_STOP=1 \
        -c "
            SELECT DISTINCT
                '$svc',
                sg_subsistema,
                sg_uf,
                nu_competencia,
                no_dbc_origem,
                no_schema,
                no_tabela
            FROM $lista
            WHERE sg_sistema='SIH'
              AND coalesce(st_existe_sql,0)=1
              AND nu_competencia
                  BETWEEN $SIH_FROM AND $SIH_TO
              AND $temporal
            ORDER BY
                sg_subsistema,
                sg_uf,
                nu_competencia,
                no_dbc_origem,
                no_tabela;
        " >> "$MANIFEST"
done

echo \
"manifest_rows=$(( $(wc -l < "$MANIFEST") - 1 ))"


# ======================================================================
# 4. SIH POSTGRESQL -> PARQUET
#
# Snapshot bruto:
#   - um Parquet por DBC
#   - sem normalização destrutiva
#   - adiciona somente proveniência SUSLake
#   - dois processos: bureta + pipeta
# ======================================================================

RESULTS="$RUN/sih_parquet_results.tsv"

printf \
'service\tsubsystem\tuf\tcompetencia\tdbc\tschema\ttable\tstatus\tsource_rows\tparquet_rows\tbytes\tpath\n' \
> "$RESULTS"


transpose_one() {

    local svc="$1"
    local sub="$2"
    local uf="$3"
    local comp="$4"
    local dbc="$5"
    local schema="$6"
    local table="$7"

    # impede injeção acidental de identificadores oriundos do catálogo
    if [[ ! "$schema" =~ ^[A-Za-z0-9_]+$ \
       || ! "$table" =~ ^[A-Za-z0-9_]+$ \
       || ! "$dbc" =~ ^[A-Za-z0-9_.-]+$ ]]
    then
        append_tsv "$RESULTS" \
            "$svc"$'\t'"$sub"$'\t'"$uf"$'\t'"$comp"$'\t'"$dbc"$'\t'"$schema"$'\t'"$table"$'\t'INVALID_NAME
        return
    fi

    local dir
    dir="$STAGE/service=$svc/subsystem=$sub/competencia=$comp/uf=$uf"

    local stem="${dbc%.*}"
    local out="$dir/${stem}.parquet"
    local tmp="$dir/.${stem}.partial.$BASHPID.parquet"

    local log
    log="$RUN/parquet_logs/${svc}_${sub}_${uf}_${comp}_${stem}.log"

    mkdir -p "$dir"

    local src_rows

    if ! src_rows="$(
        psql "service=$svc" \
            -X \
            -Atq \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT count(*)
                FROM \"$schema\".\"$table\";
            " 2>>"$log"
    )"
    then
        append_tsv "$RESULTS" \
            "$svc"$'\t'"$sub"$'\t'"$uf"$'\t'"$comp"$'\t'"$dbc"$'\t'"$schema"$'\t'"$table"$'\t'SOURCE_COUNT_ERROR
        return
    fi

    # retomada idempotente
    if [[ -s "$out" ]]; then

        local existing

        existing="$(
            duckdb -csv -c "
                SELECT count(*) AS n
                FROM read_parquet('$out');
            " 2>/dev/null |
            tail -n 1 |
            tr -d '\r' ||
            true
        )"

        if [[ "$existing" == "$src_rows" ]]; then

            local bytes
            bytes="$(stat -c %s "$out")"

            append_tsv "$RESULTS" \
                "$svc"$'\t'"$sub"$'\t'"$uf"$'\t'"$comp"$'\t'"$dbc"$'\t'"$schema"$'\t'"$table"$'\t'SKIP_OK$'\t'"$src_rows"$'\t'"$existing"$'\t'"$bytes"$'\t'"$out"

            return
        fi
    fi

    rm -f "$tmp"

    if ! nice -n 10 duckdb -c "
        LOAD postgres;

        SET threads=$DUCK_THREADS;

        ATTACH 'service=$svc'
            AS pg
            (TYPE postgres, READ_ONLY);

        COPY (
            SELECT
                t.*,

                '$svc'::VARCHAR
                    AS _suslake_source_service,

                '$dbc'::VARCHAR
                    AS _suslake_source_dbc,

                '$schema'::VARCHAR
                    AS _suslake_source_schema,

                '$table'::VARCHAR
                    AS _suslake_source_table,

                '$sub'::VARCHAR
                    AS _suslake_source_subsystem,

                '$uf'::VARCHAR
                    AS _suslake_source_uf,

                '$comp'::VARCHAR
                    AS _suslake_source_competencia

            FROM pg.\"$schema\".\"$table\" t
        )
        TO '$tmp'
        (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            ROW_GROUP_SIZE 122880
        );

        DETACH pg;
    " >"$log" 2>&1
    then

        rm -f "$tmp"

        append_tsv "$RESULTS" \
            "$svc"$'\t'"$sub"$'\t'"$uf"$'\t'"$comp"$'\t'"$dbc"$'\t'"$schema"$'\t'"$table"$'\t'DUCKDB_ERROR$'\t'"$src_rows"

        return
    fi

    local pq_rows

    pq_rows="$(
        duckdb -csv -c "
            SELECT count(*) AS n
            FROM read_parquet('$tmp');
        " |
        tail -n 1 |
        tr -d '\r'
    )"

    if [[ "$pq_rows" != "$src_rows" ]]; then

        append_tsv "$RESULTS" \
            "$svc"$'\t'"$sub"$'\t'"$uf"$'\t'"$comp"$'\t'"$dbc"$'\t'"$schema"$'\t'"$table"$'\t'COUNT_MISMATCH$'\t'"$src_rows"$'\t'"$pq_rows"$'\t'0$'\t'"$tmp"

        rm -f "$tmp"

        return
    fi

    mv -f "$tmp" "$out"

    local bytes
    bytes="$(stat -c %s "$out")"

    append_tsv "$RESULTS" \
        "$svc"$'\t'"$sub"$'\t'"$uf"$'\t'"$comp"$'\t'"$dbc"$'\t'"$schema"$'\t'"$table"$'\t'OK$'\t'"$src_rows"$'\t'"$pq_rows"$'\t'"$bytes"$'\t'"$out"
}


transpose_service() {

    local wanted="$1"

    while IFS=$'\t' read -r \
        svc sub uf comp dbc schema table
    do

        [[ "$svc" == service ]] && continue
        [[ "$svc" == "$wanted" ]] || continue

        echo \
"PARQUET $svc $sub $uf $comp $dbc"

        transpose_one \
            "$svc" \
            "$sub" \
            "$uf" \
            "$comp" \
            "$dbc" \
            "$schema" \
            "$table"

    done < "$MANIFEST"
}


echo "=== TRANSPOSE SIH ==="

# um leitor em bureta e um em pipeta
transpose_service bureta &
p1=$!

transpose_service pipeta &
p2=$!

wait "$p1"
rc1=$?

wait "$p2"
rc2=$?

echo \
"transpose_rc_bureta=$rc1 transpose_rc_pipeta=$rc2"


# ======================================================================
# 5. SUMÁRIO
# ======================================================================

SUMMARY="$RUN/summary.txt"

{
    echo "run=$RUN"
    echo "sih_from=$SIH_FROM"
    echo "sih_to=$SIH_TO"

    echo \
"manifest_rows=$(( $(wc -l < "$MANIFEST") - 1 ))"

    echo
    echo "PARQUET_STATUS"

    awk -F'\t' '
        NR>1 { n[$8]++ }
        END {
            for (k in n)
                print k,n[k]
        }
    ' "$RESULTS" |
    sort

    echo
    echo "SIH_QC_STATUS"

    awk -F'\t' '
        NR>1 { n[$4]++ }
        END {
            for (k in n)
                print k,n[k]
        }
    ' "$QC_SIH" |
    sort

    echo
    echo "SIH_QC_NONZERO"

    awk -F'\t' '
        NR>1 &&
        $4=="OK" &&
        (
             $9+0 > 0 ||
            $10+0 > 0 ||
            $13+0 > 0 ||
            $14+0 > 0 ||
            $15+0 > 0 ||
            $16+0 > 0 ||
            $17+0 > 0 ||
            $18+0 > 0
        ) {
            print
        }
    ' "$QC_SIH"

    echo
    echo "SIA_QC_FAILURES"

    awk -F'\t' '
        NR>1 &&
        ($4 != 0 || $5 != 0) {
            print
        }
    ' "$QC_SIA"

} > "$SUMMARY"

cat "$SUMMARY"

echo "OVERNIGHT_DONE"
