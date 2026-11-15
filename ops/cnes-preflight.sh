#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
TERR="$LAKE_ROOT/state/reference/territorio_current_complete.ok"
HTTP_BASE="${CNES_HTTP_TEST_BASE:-http://127.0.0.1:8766/files}"
HTTP_HOST="${CNES_HTTP_TEST_HOST:-dados.labx.ia.br}"

[[ -f "$TERR" ]] || {
  echo "ERRO: gate territorial ausente: $TERR" >&2
  exit 20
}

echo "TERRITORIO_OK"
cat "$TERR"

if [[ -d /etc/apache2 ]]; then
  conf=/etc/apache2/conf-available/labx-suslake-private.conf
  vhost=/etc/apache2/conf-available/labx-public-parquet.conf
  if [[ ! -f "$conf" ]]; then
    echo "ERRO: fragmento privado ausente: $conf" >&2
    exit 21
  fi
  if [[ ! -f "$vhost" ]] || ! grep -Fq       "IncludeOptional /etc/apache2/conf-available/labx-suslake-private.conf" "$vhost"; then
    echo "ERRO: vhost :8766 nao inclui o guard privado" >&2
    echo "Execute: sudo $ROOT/ops/apache/install-labx-private-guard.sh" >&2
    exit 21
  fi
  echo "APACHE_PRIVATE_CONF_OK $conf included_by=$vhost"

  command -v curl >/dev/null 2>&1 || {
    echo "ERRO: curl ausente; nao foi possivel testar protecao HTTP" >&2
    exit 22
  }

  private_url="$HTTP_BASE/suslake/state/reference/territorio_current_complete.ok"
  private_code="$(
    curl -sS -o /dev/null -w '%{http_code}'       -H "Host: $HTTP_HOST"       "$private_url"
  )"

  if [[ "$private_code" != "403" ]]; then
    echo "ERRO: arquivo privado real nao retornou HTTP 403: $private_url -> $private_code" >&2
    exit 23
  fi
  echo "APACHE_PRIVATE_HTTP_OK $private_url -> HTTP $private_code"

  public_file="$LAKE_ROOT/silver/sigtap/tb_procedimento/temporal.parquet"
  if [[ -f "$public_file" ]]; then
    public_url="$HTTP_BASE/suslake/silver/sigtap/tb_procedimento/temporal.parquet"
    public_code="$(
      curl -sS -o /dev/null -w '%{http_code}'         -H "Host: $HTTP_HOST"         "$public_url"
    )"
    if [[ "$public_code" != "200" && "$public_code" != "206" ]]; then
      echo "ERRO: arquivo publico de controle indisponivel: $public_url -> $public_code" >&2
      exit 24
    fi
    echo "APACHE_PUBLIC_HTTP_OK $public_url -> HTTP $public_code"
  fi
else
  echo "WARN: /etc/apache2 ausente; nao foi possivel validar configuracao privada"
fi

echo "CNES_PREFLIGHT_OK"
