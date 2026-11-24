#!/usr/bin/env bash
set -Eeuo pipefail

FTP_ROOT="${TERRITORIO_FTP_ROOT:-ftp://ftp.datasus.gov.br/territorio/tabelas}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
YEAR="$(date +%Y)"
ZIP_NAME=""

usage() {
  cat <<'USAGE'
Uso:
  ops/territorio-acquire.sh [--year AAAA] [--zip-name ARQUIVO.zip]

Lista o diretorio anual oficial do DATASUS e baixa o ZIP territorial mais
recente. O Raw e preservado por ano/snapshot e SHA-256.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --year) YEAR="$2"; shift 2 ;;
    --zip-name) ZIP_NAME="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
  esac
done

[[ "$YEAR" =~ ^[0-9]{4}$ ]] || { echo "ERRO: ano invalido: $YEAR" >&2; exit 2; }

for c in curl unzip sha256sum stat sort sed grep; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done

BASE="$FTP_ROOT/$YEAR"
RAW="$LAKE_ROOT/raw/reference/territorio"
STATE="$LAKE_ROOT/state/reference"
mkdir -p "$RAW" "$STATE"

if [[ -z "$ZIP_NAME" ]]; then
  listing="$(mktemp)"
  trap 'rm -f "$listing"' EXIT
  curl -fsS --list-only "$BASE/" | tr -d '\r' > "$listing"
  ZIP_NAME="$(
    grep -Ei '(^|[-_])base[_-]?territorial.*\.zip$' "$listing"       | sort -V       | tail -1
  )"
fi

[[ -n "$ZIP_NAME" ]] || { echo "ERRO: nenhum ZIP territorial encontrado em $BASE/" >&2; exit 4; }
[[ "$ZIP_NAME" == "$(basename "$ZIP_NAME")" ]] || { echo "ERRO: --zip-name deve ser nome simples" >&2; exit 4; }

month="$(printf '%s\n' "$ZIP_NAME" | sed -nE 's/^([0-9]{2})[-_].*/\1/p')"
if [[ -n "$month" && "$month" =~ ^(0[1-9]|1[0-2])$ ]]; then
  snapshot="${YEAR}${month}"
else
  snapshot="${YEAR}00"
fi

destdir="$RAW/year=$YEAR/snapshot=$snapshot"
dest="$destdir/$ZIP_NAME"
mkdir -p "$destdir"

if [[ ! -f "$dest" ]]; then
  partial="$dest.partial.$$"
  rm -f "$partial"
  echo "DOWNLOAD $BASE/$ZIP_NAME"
  curl --fail --location --silent --show-error --retry 4 --retry-delay 3     --remote-time --output "$partial" "$BASE/$ZIP_NAME"
  unzip -tq "$partial" >/dev/null
  mv "$partial" "$dest"
else
  unzip -tq "$dest" >/dev/null
  echo "RAW_EXISTENTE $dest"
fi

sha="$(sha256sum "$dest" | awk '{print $1}')"
bytes="$(stat -c %s "$dest")"
snapshot_marker="$STATE/territorio_${snapshot}.raw.ok"
{
  echo "year=$YEAR"
  echo "snapshot=$snapshot"
  echo "timestamp=$(date -Is)"
  echo "source=$BASE/$ZIP_NAME"
  echo "file=$ZIP_NAME"
  echo "bytes=$bytes"
  echo "sha256=$sha"
  echo "path=$dest"
} > "$snapshot_marker"

latest="$STATE/territorio_latest.ok"
latest_snapshot=""
[[ -f "$latest" ]] && latest_snapshot="$(sed -n 's/^snapshot=//p' "$latest" | head -1)"
if [[ -z "$latest_snapshot" || "$snapshot" > "$latest_snapshot" || "$snapshot" == "$latest_snapshot" ]]; then
  cp "$snapshot_marker" "$latest"
fi

echo "TERRITORIO_RAW_OK year=$YEAR snapshot=$snapshot bytes=$bytes sha256=$sha"
echo "marker=$snapshot_marker"
echo "latest=$latest"
