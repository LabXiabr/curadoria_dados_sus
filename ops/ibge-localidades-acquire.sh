#!/usr/bin/env bash
set -Eeuo pipefail
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
YEAR="${IBGE_LOCALIDADES_YEAR:-2022}"
URL="${IBGE_LOCALIDADES_URL:-https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/Localidades_do_Brasil/2022/Localidades_Brasil_gpkg.zip}"
RAW="$LAKE_ROOT/raw/reference/ibge_localidades/year=$YEAR"
STATE="$LAKE_ROOT/state/reference"
FILE="${URL##*/}"
DEST="$RAW/$FILE"
for c in curl unzip sha256sum stat; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done
mkdir -p "$RAW" "$STATE"
if [[ ! -f "$DEST" ]]; then
  partial="$DEST.partial.$$"
  rm -f "$partial"
  echo "DOWNLOAD $URL"
  curl --fail --location --silent --show-error --retry 4 --retry-delay 3 --remote-time --output "$partial" "$URL"
  unzip -tq "$partial" >/dev/null
  mv "$partial" "$DEST"
else
  unzip -tq "$DEST" >/dev/null
  echo "RAW_EXISTENTE $DEST"
fi
sha="$(sha256sum "$DEST" | awk '{print $1}')"
bytes="$(stat -c %s "$DEST")"
marker="$STATE/ibge_localidades_${YEAR}.raw.ok"
{
  echo "year=$YEAR"
  echo "timestamp=$(date -Is)"
  echo "source=$URL"
  echo "file=$FILE"
  echo "bytes=$bytes"
  echo "sha256=$sha"
  echo "path=$DEST"
} > "$marker"
echo "IBGE_LOCALIDADES_RAW_OK year=$YEAR bytes=$bytes sha256=$sha"
echo "marker=$marker"
