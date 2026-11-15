#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
ENV_FILE="${CURADORIA_PSQL_ENV:-$HOME/etl_ftp_sus_parquet/.env}"
STATE="$LAKE_ROOT/state/psql"
mkdir -p "$STATE"

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

command -v psql >/dev/null || {
  echo "ERRO: psql ausente" >&2
  exit 42
}

ts="$(date +%Y%m%d_%H%M%S)"
out="$STATE/cnes_retirement_inventory_${ts}.tsv"

PGPASSWORD="$BURETA_DB_PASSWORD" psql   -h "$BURETA_HOST" -p "$BURETA_DB_PORT"   -U "$BURETA_DB_USER" -d "$BURETA_DB_NAME"   -Atq -F $'\t' -v ON_ERROR_STOP=1 <<'SQL' > "$out"
WITH colflags AS (
  SELECT
    table_schema,
    table_name,
    bool_or(lower(column_name)='co_cnes') AS has_co_cnes,
    bool_or(lower(column_name)='co_unidade') AS has_co_unidade,
    bool_or(lower(column_name)='co_profissional_sus') AS has_co_profissional_sus,
    bool_or(lower(column_name) IN ('competencia','ano_mes','dt_competencia','co_competencia')) AS has_competencia
  FROM information_schema.columns
  WHERE table_schema NOT IN ('pg_catalog','information_schema')
  GROUP BY 1,2
),
rels AS (
  SELECT
    n.nspname AS table_schema,
    c.relname AS table_name,
    pg_total_relation_size(c.oid)::bigint AS total_bytes,
    greatest(c.reltuples,0)::bigint AS estimated_rows
  FROM pg_class c
  JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE c.relkind IN ('r','p')
    AND n.nspname NOT IN ('pg_catalog','information_schema')
)
SELECT
  r.table_schema,
  r.table_name,
  r.total_bytes,
  r.estimated_rows,
  coalesce(f.has_co_cnes,false)::int,
  coalesce(f.has_co_unidade,false)::int,
  coalesce(f.has_co_profissional_sus,false)::int,
  coalesce(f.has_competencia,false)::int,
  CASE
    WHEN lower(r.table_schema||'.'||r.table_name) LIKE '%cnes%'
      THEN 'candidate_cnes_named'
    WHEN coalesce(f.has_co_unidade,false)
      AND coalesce(f.has_co_profissional_sus,false)
      THEN 'candidate_cnes_professional'
    WHEN coalesce(f.has_co_cnes,false)
      THEN 'cross_system_has_co_cnes_review_only'
    ELSE 'other'
  END AS retirement_class
FROM rels r
LEFT JOIN colflags f USING (table_schema,table_name)
WHERE lower(r.table_schema||'.'||r.table_name) LIKE '%cnes%'
   OR coalesce(f.has_co_unidade,false)
   OR coalesce(f.has_co_cnes,false)
   OR coalesce(f.has_co_profissional_sus,false)
ORDER BY r.total_bytes DESC, r.table_schema, r.table_name;
SQL

marker="$STATE/cnes_retirement_inventory_current.ok"
{
  echo "timestamp=$ts"
  echo "report=$out"
  echo "mode=read_only_inventory"
  echo "drop=never_automatic"
  echo "status=complete"
} > "$marker"

echo "CNES_PSQL_RETIREMENT_INVENTORY_OK report=$out"
column -ts $'\t' "$out" | head -50
