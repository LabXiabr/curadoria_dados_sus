#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
TABNET_REPO="${TABNET_POP_REPO:-/dados/abertos/repos/tabnet-populacao}"
REPO_URL="${TABNET_POP_REPO_URL:-https://github.com/LabXiabr/tabnet-populacao.git}"
ANO="2024"

usage() {
    echo "Uso: ops/populacao-tabnet-to-lake.sh [--ano AAAA] [--repo CAMINHO]"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --ano) ANO="$2"; shift 2 ;;
        --repo) TABNET_REPO="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
    esac
done
[[ "$ANO" =~ ^[0-9]{4}$ ]] || { echo "ERRO: ano invalido" >&2; exit 2; }

for c in git python3 sha256sum duckdb; do
    command -v "$c" >/dev/null 2>&1 || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done

mkdir -p "$LAKE_ROOT/raw/reference/populacao_tabnet"          "$LAKE_ROOT/bronze/reference/populacao_tabnet"          "$LAKE_ROOT/silver/reference/populacao"          "$LAKE_ROOT/state/reference"          "$LAKE_ROOT/work"

if [[ ! -d "$TABNET_REPO/.git" ]]; then
    git clone "$REPO_URL" "$TABNET_REPO"
else
    git -C "$TABNET_REPO" pull --ff-only
fi

VENV="$TABNET_REPO/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
    python3 -m venv "$VENV"
fi

req_sha="$(sha256sum "$TABNET_REPO/requirements.txt" | awk '{print $1}')"
req_marker="$VENV/.requirements.sha256"
if [[ ! -f "$req_marker" || "$(cat "$req_marker")" != "$req_sha" ]]; then
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install -r "$TABNET_REPO/requirements.txt"
    printf '%s\n' "$req_sha" > "$req_marker"
fi

commit="$(git -C "$TABNET_REPO" rev-parse HEAD)"
work="$(mktemp -d "$LAKE_ROOT/work/populacao_${ANO}_XXXXXX")"
trap 'rm -rf "$work"' EXIT

(
    cd "$TABNET_REPO"
    "$VENV/bin/python" -m src.tabnet_populacao         --ano "$ANO"         --saida "$work"         --debug
)

csv="$work/populacao_${ANO}.csv"
meta="$work/metadados_${ANO}.json"
[[ -s "$csv" && -s "$meta" ]] || { echo "ERRO: extracao nao gerou CSV/metadados" >&2; exit 10; }

resp_sha="$(python3 - "$meta" <<'PY'
import json,sys
print(json.load(open(sys.argv[1],encoding="utf-8"))["sha256_resposta"])
PY
)"

rawdir="$LAKE_ROOT/raw/reference/populacao_tabnet/ano=$ANO/sha256=$resp_sha"
mkdir -p "$rawdir"
cp -a "$csv" "$meta" "$rawdir/"
[[ -d "$work/diagnostico" ]] && cp -a "$work/diagnostico" "$rawdir/"

bronzedir="$LAKE_ROOT/bronze/reference/populacao_tabnet/ano=$ANO/source_sha256=$resp_sha"
mkdir -p "$bronzedir"
bronze="$bronzedir/part-000.parquet"
partial="$bronze.partial.$$"

duckdb -c "
COPY (
 SELECT
   CAST(ano AS INTEGER) AS ano,
   CAST(uf AS VARCHAR) AS uf,
   CAST(cod_municipio AS VARCHAR) AS co_municipio,
   CAST(municipio AS VARCHAR) AS no_municipio,
   CAST(populacao AS BIGINT) AS populacao,
   '$resp_sha'::VARCHAR AS _source_response_sha256,
   '$commit'::VARCHAR AS _source_repository_commit,
   current_timestamp AS _ingested_at
 FROM read_csv_auto('$csv', header=true, all_varchar=true, sample_size=-1)
)
TO '$partial' (FORMAT PARQUET, COMPRESSION ZSTD);
"
mv -f "$partial" "$bronze"

silverdir="$LAKE_ROOT/silver/reference/populacao/ano=$ANO"
mkdir -p "$silverdir"
silver="$silverdir/part-000.parquet"
duckdb -c "
COPY (
 SELECT * FROM read_parquet('$bronze')
)
TO '$silver.partial.$$' (FORMAT PARQUET, COMPRESSION ZSTD);
"
mv -f "$silver.partial.$$" "$silver"

read -r rows mun ufs total < <(
duckdb -csv -noheader -c "
SELECT count(*), count(DISTINCT co_municipio), count(DISTINCT uf), sum(populacao)
FROM read_parquet('$silver');
" | tr ',' ' '
)

[[ "$rows" == "$mun" ]] || { echo "ERRO: municipios duplicados rows=$rows distinct=$mun" >&2; exit 20; }
(( rows >= 5000 )) || { echo "ERRO: cobertura municipal insuficiente: $rows" >&2; exit 20; }
[[ "$ufs" == "27" ]] || { echo "ERRO: UFs=$ufs, esperado 27" >&2; exit 20; }

marker="$LAKE_ROOT/state/reference/populacao_${ANO}.ok"
{
    echo "ano=$ANO"
    echo "timestamp=$(date -Is)"
    echo "source_repository=$REPO_URL"
    echo "source_commit=$commit"
    echo "response_sha256=$resp_sha"
    echo "municipios=$mun"
    echo "ufs=$ufs"
    echo "populacao_total=$total"
    echo "raw=$rawdir"
    echo "bronze=$bronze"
    echo "silver=$silver"
} > "$marker"

echo "POPULACAO_REFERENCE_OK ano=$ANO municipios=$mun ufs=$ufs total=$total"
echo "marker=$marker"
