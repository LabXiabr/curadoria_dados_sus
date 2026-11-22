#!/usr/bin/env bash
set -Eeuo pipefail

FTP_BASE="${CNES_FTP_BASE:-ftp://ftp.datasus.gov.br/cnes}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
RAW="$LAKE_ROOT/raw/cnes/reference"
STATE="$LAKE_ROOT/state/cnes"

ARTIFACT=""

usage() {
    cat <<'USAGE'
Uso:
  ops/cnes-acquire-reference.sh --artifact cep|municipios

Baixa arquivos de aplicacao CNES sem competencia no nome e os versiona
por SHA-256. Cada observacao e registrada mesmo quando o conteudo nao mudou.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --artifact) ARTIFACT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
    esac
done

case "$ARTIFACT" in
    cep)
        slug="cep_brasil"
        filename="CEP_BRASIL.ZIP"
        ;;
    municipios)
        slug="municipios_brasil"
        filename="Municipio_Brasil.ZIP"
        ;;
    *)
        echo "ERRO: --artifact deve ser cep ou municipios" >&2
        exit 2
        ;;
esac

for c in curl unzip sha256sum stat; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 3
    }
done

mkdir -p "$RAW/$slug" "$STATE"
tmp="$(mktemp --suffix=.zip)"
trap 'rm -f "$tmp"' EXIT

url="$FTP_BASE/$filename"
curl --fail --location --silent --show-error --retry 4 --retry-delay 3     --remote-time --output "$tmp" "$url"
unzip -tq "$tmp" >/dev/null

sha="$(sha256sum "$tmp" | awk '{print $1}')"
bytes="$(stat -c %s "$tmp")"
mtime="$(stat -c %y "$tmp")"
version_dir="$RAW/$slug/sha256=$sha"
dest="$version_dir/$filename"
mkdir -p "$version_dir"

if [[ ! -f "$dest" ]]; then
    mv "$tmp" "$dest"
    echo "NOVA_VERSAO $dest"
else
    echo "VERSAO_JA_EXISTE $dest"
fi

obs="$STATE/reference_observations.tsv"
if [[ ! -f "$obs" ]]; then
    printf 'artifact\tobserved_at\tremote_url\tremote_mtime\tbytes\tsha256\tpath\n' > "$obs"
fi
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n'     "$slug" "$(date -Is)" "$url" "$mtime" "$bytes" "$sha" "$dest" >> "$obs"

marker="$STATE/reference_${slug}_latest.ok"
{
    echo "artifact=$slug"
    echo "observed_at=$(date -Is)"
    echo "remote_url=$url"
    echo "remote_mtime=$mtime"
    echo "bytes=$bytes"
    echo "sha256=$sha"
    echo "path=$dest"
} > "$marker"

echo "CNES_REFERENCE_OK artifact=$slug sha256=$sha bytes=$bytes"
echo "path=$dest"
echo "marker=$marker"
