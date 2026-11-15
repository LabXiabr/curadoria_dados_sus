#!/usr/bin/env bash
set -Eeuo pipefail

command -v wine >/dev/null || {
  echo "ERRO: wine ausente; recomposicao DBC futura depende da ETL Wine existente" >&2
  exit 3
}

echo "DISSEMIN_DBC_WINE_PREFLIGHT_OK"
echo "nota=fluxo atual de migracao usa PostgreSQL; Wine somente para recomposicao DBC"
