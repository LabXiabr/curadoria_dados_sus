#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
TERR="$LAKE_ROOT/state/reference/territorio_current_complete.ok"

[[ -f "$TERR" ]] || {
  echo "ERRO: gate territorial ausente: $TERR" >&2
  exit 20
}

echo "TERRITORIO_OK"
cat "$TERR"

if [[ -d /etc/apache2 ]]; then
  conf=/etc/apache2/conf-enabled/labx-suslake-private.conf
  if [[ ! -e "$conf" ]]; then
    echo "ERRO: protecao Apache do suslake privado nao esta habilitada: $conf" >&2
    echo "Instale ops/apache/labx-suslake-private.conf antes de carregar CNES Bronze." >&2
    exit 21
  fi
  echo "APACHE_PRIVATE_CONF_OK $conf"
else
  echo "WARN: /etc/apache2 ausente; nao foi possivel validar configuracao privada"
fi

echo "CNES_PREFLIGHT_OK"
