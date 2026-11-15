#!/usr/bin/env bash
set -Eeuo pipefail

FTP_BASE="${CNES_FTP_BASE:-ftp://ftp.datasus.gov.br/cnes}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
RAW="$LAKE_ROOT/raw/cnes/base_dados"
STATE="$LAKE_ROOT/state/cnes"
LOGROOT="$LAKE_ROOT/logs/cnes"

COMP="latest"

usage() {
    cat <<'USAGE'
Uso:
  ops/cnes-acquire-base.sh [--competencia YYYYMM|latest]

Baixa o snapshot oficial BASE_DE_DADOS_CNES_AAAAMM.ZIP.
O Raw e imutavel e particionado por competencia.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --competencia) COMP="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
    esac
done

[[ "$COMP" == "latest" || "$COMP" =~ ^[0-9]{6}$ ]] || {
    echo "ERRO: competencia invalida: $COMP" >&2
    exit 2
}

for c in curl unzip sha256sum awk sed sort stat; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 3
    }
done

mkdir -p "$RAW" "$STATE" "$LOGROOT"

names="$(mktemp)"
trap 'rm -f "$names"' EXIT

curl --fail --silent --show-error --list-only "$FTP_BASE/" \
    | tr -d '\r' \
    | grep -Ei '^BASE_DE_DADOS_CNES_[0-9]{6}\.ZIP$' \
    | sort -u > "$names"

if [[ "$COMP" == "latest" ]]; then
    selected="$(sort "$names" | tail -1)"
else
    selected="$(grep -Ei "^BASE_DE_DADOS_CNES_${COMP}\.ZIP$" "$names" | tail -1 || true)"
fi

[[ -n "$selected" ]] || {
    echo "ERRO: snapshot CNES nao encontrado para $COMP em $FTP_BASE" >&2
    exit 4
}

competencia="$(printf '%s\n' "$selected" | sed -nE 's/^BASE_DE_DADOS_CNES_([0-9]{6})\.ZIP$/\1/Ip')"
destdir="$RAW/competencia=$competencia"
dest="$destdir/$selected"
mkdir -p "$destdir"

if [[ ! -f "$dest" ]]; then
    partial="$dest.partial.$$"
    rm -f "$partial"
    echo "DOWNLOAD $FTP_BASE/$selected"
    curl --fail --location --silent --show-error --retry 4 --retry-delay 3 \
        --remote-time --output "$partial" "$FTP_BASE/$selected"
    unzip -tq "$partial" >/dev/null
    mv "$partial" "$dest"
else
    unzip -tq "$dest" >/dev/null
    echo "RAW_EXISTENTE $dest"
fi

sha="$(sha256sum "$dest" | awk '{print $1}')"
bytes="$(stat -c %s "$dest")"
marker="$STATE/raw_base_${competencia}.ok"

{
    echo "competencia=$competencia"
    echo "timestamp=$(date -Is)"
    echo "source=$FTP_BASE/$selected"
    echo "file=$selected"
    echo "bytes=$bytes"
    echo "sha256=$sha"
    echo "path=$dest"
} > "$marker"

echo "CNES_RAW_OK competencia=$competencia bytes=$bytes sha256=$sha"
echo "marker=$marker"
