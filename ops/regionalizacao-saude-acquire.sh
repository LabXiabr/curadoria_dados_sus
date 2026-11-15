#!/usr/bin/env bash
set -Eeuo pipefail

URL="${REGIONALIZACAO_SAUDE_URL:-https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/dbgeral/macroregiao_de_saude_csv.zip}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
RAW="$LAKE_ROOT/raw/reference/regionalizacao_saude"
STATE="$LAKE_ROOT/state/reference"

for c in curl unzip sha256sum stat; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done

mkdir -p "$RAW" "$STATE"
tmp="$(mktemp --suffix=.zip)"
trap 'rm -f "$tmp"' EXIT

curl --fail --location --silent --show-error --retry 4 --retry-delay 3   --remote-time --output "$tmp" "$URL"
unzip -tq "$tmp" >/dev/null

sha="$(sha256sum "$tmp" | awk '{print $1}')"
bytes="$(stat -c %s "$tmp")"
version="${sha:0:16}"
destdir="$RAW/version=$version"
dest="$destdir/macroregiao_de_saude_csv.zip"
mkdir -p "$destdir"

if [[ ! -f "$dest" ]]; then
  mv "$tmp" "$dest"
  echo "NOVA_VERSAO $dest"
else
  echo "VERSAO_JA_EXISTE $dest"
fi

marker="$STATE/regionalizacao_saude_latest.ok"
{
  echo "timestamp=$(date -Is)"
  echo "source=$URL"
  echo "bytes=$bytes"
  echo "sha256=$sha"
  echo "version=$version"
  echo "path=$dest"
} > "$marker"

echo "REGIONALIZACAO_SAUDE_RAW_OK version=$version bytes=$bytes sha256=$sha"
echo "marker=$marker"
