#!/usr/bin/env bash
set -Eeuo pipefail

MODE="dry-run"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) MODE="execute"; shift ;;
    -h|--help)
      echo "Uso: $0 [--execute]"
      echo "Padrao: dry-run."
      exit 0
      ;;
    *) echo "Parametro desconhecido: $1" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_PRIVATE="$REPO_ROOT/ops/apache/labx-suslabx-private.conf"
DST_PRIVATE="/etc/apache2/conf-available/labx-suslabx-private.conf"
PUBLIC_CONF="/etc/apache2/conf-available/labx-public-parquet.conf"
ENABLED_PUBLIC="/etc/apache2/conf-enabled/labx-public-parquet.conf"
STAMP="$(date '+%Y%m%d_%H%M%S')"

die(){ echo "ERRO: $*" >&2; exit 1; }
log(){ printf '[%s] %s
' "$(date '+%F %T')" "$*"; }

[[ -f "$SRC_PRIVATE" ]] || die "arquivo Git ausente: $SRC_PRIVATE"
[[ -f "$PUBLIC_CONF" ]] || die "Apache public conf ausente: $PUBLIC_CONF"

log "Modo: $MODE"
log "Private: $SRC_PRIVATE -> $DST_PRIVATE"
log "Public: trocar labx-suslake-private.conf -> labx-suslabx-private.conf em $PUBLIC_CONF"

if [[ "$MODE" != "execute" ]]; then
  grep -nE 'suslake|suslabx' "$PUBLIC_CONF" || true
  log "DRY_RUN: nenhuma alteracao realizada"
  exit 0
fi

sudo install -m 0644 "$SRC_PRIVATE" "$DST_PRIVATE"
sudo cp -a "$PUBLIC_CONF" "${PUBLIC_CONF}.bak_suslabx_${STAMP}"
sudo sed -i 's#labx-suslake-private\.conf#labx-suslabx-private.conf#g' "$PUBLIC_CONF"

if grep -q 'labx-suslake-private\.conf' "$PUBLIC_CONF"; then
  die "include antigo permaneceu em $PUBLIC_CONF"
fi
grep -q 'labx-suslabx-private\.conf' "$PUBLIC_CONF" || die "include novo nao encontrado"

sudo apachectl configtest
sudo systemctl reload apache2

# Valida o arquivo efetivamente habilitado quando houver symlink do conf-enabled.
if [[ -f "$ENABLED_PUBLIC" ]] && grep -q 'labx-suslake-private\.conf' "$ENABLED_PUBLIC"; then
  die "conf-enabled ainda referencia suslake: $ENABLED_PUBLIC"
fi

log "APACHE_SUSLABX_OK"
log "Backup: ${PUBLIC_CONF}.bak_suslabx_${STAMP}"
