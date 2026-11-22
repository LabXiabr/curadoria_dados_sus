#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
OLD_ROOT="${OLD_ROOT:-/dados/abertos/suslake}"
APACHE_PUBLIC_CONF="${APACHE_PUBLIC_CONF:-/etc/apache2/conf-enabled/labx-public-parquet.conf}"
APACHE_PRIVATE_CONF="${APACHE_PRIVATE_CONF:-/etc/apache2/conf-available/labx-suslabx-private.conf}"

fail=0
ok(){ printf 'OK	%s
' "$*"; }
warn(){ printf 'WARN	%s
' "$*"; }
bad(){ printf 'FAIL	%s
' "$*"; fail=1; }

if [[ -d "$LAKE_ROOT" ]]; then
  ok "lake_root=$LAKE_ROOT"
else
  bad "lake_root ausente: $LAKE_ROOT"
fi

if [[ ! -e "$OLD_ROOT" ]]; then
  ok "old_root ausente"
else
  bad "old_root ainda existe: $OLD_ROOT"
fi

for d in raw bronze silver state; do
  if [[ -d "$LAKE_ROOT/$d" ]]; then
    ok "diretorio $d"
  else
    bad "diretorio ausente: $LAKE_ROOT/$d"
  fi
done

if [[ -f "$APACHE_PRIVATE_CONF" ]]; then
  ok "apache private conf suslabx presente"
else
  bad "apache private conf ausente: $APACHE_PRIVATE_CONF"
fi

if [[ -f "$APACHE_PUBLIC_CONF" ]]; then
  if grep -q 'labx-suslabx-private\.conf' "$APACHE_PUBLIC_CONF"; then
    ok "apache include aponta para suslabx"
  else
    bad "apache include nao aponta para labx-suslabx-private.conf"
  fi
  if grep -Eqi 'labx-suslake-private\.conf|/dados/abertos/suslake|/files/suslake' "$APACHE_PUBLIC_CONF"; then
    bad "apache ativo ainda contem referencia operacional SUSLake"
  else
    ok "apache ativo sem referencia operacional SUSLake"
  fi
else
  warn "apache public conf nao encontrado: $APACHE_PUBLIC_CONF"
fi

if command -v apachectl >/dev/null 2>&1; then
  if apachectl configtest >/tmp/suslabx_apache_configtest.$$ 2>&1; then
    ok "apachectl configtest"
  else
    cat /tmp/suslabx_apache_configtest.$$ >&2 || true
    bad "apachectl configtest falhou"
  fi
  rm -f /tmp/suslabx_apache_configtest.$$
else
  warn "apachectl ausente"
fi

# Referencias ativas no repositorio. Historico/superseded e o proprio script de
# migracao de nome sao permitidos.
mapfile -t refs < <(
  grep -REIn --exclude-dir=.git --exclude-dir=logs --exclude='*.gz' \
    '(/dados/abertos/suslake|/files/suslake|labx-suslake-private\.conf|silver/suslake\.duckdb)' \
    "$REPO_ROOT" 2>/dev/null \
    | grep -v '/docs/modeling/DECISIONS_SUPERSEDED.md:' \
    | grep -v '/ops/rename-suslake-to-suslabx.sh:' \
    | grep -v '/ops/migrate-apache-suslabx.sh:' \
    | grep -v '/ops/apache/install-labx-private-guard.sh:' \
    | grep -v '/ops/qc-stage1-suslabx.sh:' \
    || true
)
if (( ${#refs[@]} == 0 )); then
  ok "repositorio ativo sem suslake"
else
  printf '%s
' "${refs[@]}" >&2
  bad "repositorio ativo ainda contem suslake"
fi

sql_generated="$REPO_ROOT/sql/duckdb/generated/cnes_silver_views.sql"
if [[ -f "$sql_generated" ]]; then
  if grep -qi 'suslake' "$sql_generated"; then
    bad "SQL CNES gerado ainda contem suslake"
  else
    ok "SQL CNES gerado sem suslake"
  fi
else
  warn "SQL CNES gerado ausente; sera recriado quando o catalogo CNES for reconstruido"
fi

fields="$LAKE_ROOT/state/metadata/source_fields_observed_current.tsv"
schemas="$LAKE_ROOT/state/metadata/source_schemas_observed_current.tsv"
tabnet="$LAKE_ROOT/state/metadata/tabnet/tabulator_summary.tsv"
tabnet_options="$LAKE_ROOT/state/metadata/tabnet/tabulator_options.tsv"
schema_gate="$LAKE_ROOT/state/metadata/source_schema_coverage_current.ok"

for f in "$fields" "$schemas"; do
  if [[ -s "$f" && $(wc -l < "$f") -gt 1 ]]; then
    ok "metadata $(basename "$f") linhas=$(wc -l < "$f")"
  else
    bad "metadata ausente/vazio: $f"
  fi
done

if [[ -s "$schema_gate" ]]; then
  ok "schema coverage gate presente"
else
  bad "schema coverage gate ausente: $schema_gate"
fi

if [[ -s "$tabnet" && $(wc -l < "$tabnet") -gt 1 ]]; then
  ok_count=$(awk -F '\t' 'NR>1 && $9=="ok"{n++} END{print n+0}' "$tabnet")
  err_count=$(awk -F '\t' 'NR>1 && $9!="ok"{n++} END{print n+0}' "$tabnet")
  total=$((ok_count+err_count))
  if (( ok_count > 0 )); then
    ok "tabnet metadata total=$total ok=$ok_count error=$err_count"
    if (( err_count > 0 )); then
      warn "TabNet possui falhas registradas; revisar tabulator_summary.tsv, mas o harvest foi materializado"
    fi
    if [[ -s "$tabnet_options" && $(wc -l < "$tabnet_options") -gt 1 ]]; then
      ok "tabnet options linhas=$(wc -l < "$tabnet_options")"
    else
      bad "TabNet harvest sem options materializadas: $tabnet_options"
    fi
  else
    bad "TabNet harvest sem nenhuma coleta bem-sucedida"
  fi
else
  bad "tabnet metadata ausente/vazio: $tabnet"
fi

if (( fail == 0 )); then
  echo "STAGE1_SUSLABX_OK"
  exit 0
fi

echo "STAGE1_SUSLABX_INCOMPLETE"
exit 10
