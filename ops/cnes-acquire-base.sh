#!/usr/bin/env bash
set -Eeuo pipefail

FTP_BASE="${CNES_FTP_BASE:-ftp://ftp.datasus.gov.br/cnes}"
MIN_COMP="${CNES_BASE_MIN_COMP:-201706}"
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
A serie oficial de download por competencia e considerada suportada a partir
de 201706. O Raw e imutavel e particionado por competencia.
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
[[ "$MIN_COMP" =~ ^[0-9]{6}$ ]] || {
    echo "ERRO: CNES_BASE_MIN_COMP invalida: $MIN_COMP" >&2
    exit 2
}
if [[ "$COMP" != "latest" ]] && (( 10#$COMP < 10#$MIN_COMP )); then
    echo "ERRO: BASE_DE_DADOS_CNES por competencia e suportada a partir de $MIN_COMP; solicitado=$COMP" >&2
    echo "Use o fluxo legado PostgreSQL/DBC para competencias anteriores." >&2
    exit 5
fi

for c in curl unzip sha256sum awk sed sort stat od find date; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 3
    }
done

mkdir -p "$RAW" "$STATE" "$LOGROOT"

names="$(mktemp)"
trap 'rm -f "$names"' EXIT

curl --fail --silent --show-error --list-only "$FTP_BASE/"     | tr -d '\r'     | grep -Ei '^BASE_DE_DADOS_CNES_[0-9]{6}\.ZIP$'     | sort -u > "$names"

if [[ "$COMP" == "latest" ]]; then
    selected="$(
      while IFS= read -r candidate; do
        c="$(
          printf '%s\n' "$candidate"             | sed -nE 's/^BASE_DE_DADOS_CNES_([0-9]{6})\.ZIP$/\1/Ip'
        )"
        [[ -n "$c" ]] || continue
        if (( 10#$c >= 10#$MIN_COMP )); then
          printf '%s\n' "$candidate"
        fi
      done < "$names" | sort | tail -1
    )"
else
    selected="$(grep -Ei "^BASE_DE_DADOS_CNES_${COMP}\.ZIP$" "$names" | tail -1 || true)"
fi

[[ -n "$selected" ]] || {
    echo "ERRO: snapshot CNES nao encontrado para $COMP em $FTP_BASE" >&2
    exit 4
}

competencia="$(printf '%s\n' "$selected" | sed -nE 's/^BASE_DE_DADOS_CNES_([0-9]{6})\.ZIP$/\1/Ip')"
if (( 10#$competencia < 10#$MIN_COMP )); then
    echo "ERRO: item listado no FTP e anterior ao inicio oficial suportado: $competencia < $MIN_COMP" >&2
    exit 5
fi

destdir="$RAW/competencia=$competencia"
dest="$destdir/$selected"
partial="$dest.partial"
url="$FTP_BASE/$selected"
mkdir -p "$destdir"

# Limpa apenas parciais efemeros do formato antigo com PID.
find "$destdir" -maxdepth 1 -type f -name "$selected.partial.*" -delete

if [[ -f "$dest" ]]; then
    if unzip -tq "$dest" >/dev/null 2>&1; then
        echo "RAW_EXISTENTE $dest"
    else
        echo "ERRO: Raw final existente mas ZIP invalido: $dest" >&2
        exit 20
    fi
else
    remote_bytes="$(
      curl --fail --silent --show-error --head "$url" 2>/dev/null         | tr -d '\r'         | awk 'tolower($1)=="content-length:" {print $2}'         | tail -1 || true
    )"

    ok=0
    for attempt in 1 2 3 4 5; do
        resume=()
        if [[ -s "$partial" ]]; then
            resume=(--continue-at -)
        fi

        echo "DOWNLOAD attempt=$attempt url=$url partial_bytes=$(stat -c %s "$partial" 2>/dev/null || echo 0) remote_bytes=${remote_bytes:-unknown}"

        set +e
        curl           --fail           --location           --silent           --show-error           --retry 3           --retry-all-errors           --retry-delay 3           --connect-timeout 30           --remote-time           "${resume[@]}"           --output "$partial"           "$url"
        rc=$?
        set -e

        local_bytes="$(stat -c %s "$partial" 2>/dev/null || echo 0)"

        if (( rc == 0 )) && unzip -tq "$partial" >/dev/null 2>&1; then
            if [[ -n "$remote_bytes" && "$remote_bytes" =~ ^[0-9]+$ && "$local_bytes" -ne "$remote_bytes" ]]; then
                echo "AVISO: ZIP valido mas tamanho local difere do Content-Length: local=$local_bytes remote=$remote_bytes" >&2
            fi
            mv "$partial" "$dest"
            ok=1
            break
        fi

        echo "DOWNLOAD_INVALID attempt=$attempt curl_rc=$rc local_bytes=$local_bytes remote_bytes=${remote_bytes:-unknown}" >&2
        printf 'prefix_hex=' >&2
        od -An -tx1 -N32 "$partial" 2>/dev/null | tr -d ' \n' >&2 || true
        echo >&2

        if [[ -n "$remote_bytes" && "$remote_bytes" =~ ^[0-9]+$ && "$local_bytes" -ge "$remote_bytes" ]]; then
            echo "ERRO: transferencia completa pelo tamanho remoto, mas conteudo nao e ZIP valido." >&2
            break
        fi

        sleep 3
    done

    if (( ok == 0 )); then
        echo "ERRO: nao foi possivel obter ZIP CNES valido apos tentativas: $url" >&2
        echo "Parcial mantido para diagnostico/retomada: $partial" >&2
        exit 21
    fi
fi

sha="$(sha256sum "$dest" | awk '{print $1}')"
bytes="$(stat -c %s "$dest")"
marker="$STATE/raw_base_${competencia}.ok"

{
    echo "competencia=$competencia"
    echo "timestamp=$(date -Is)"
    echo "source=$url"
    echo "official_min_competencia=$MIN_COMP"
    echo "file=$selected"
    echo "bytes=$bytes"
    echo "sha256=$sha"
    echo "path=$dest"
    echo "status=validated_zip"
} > "$marker"

echo "CNES_RAW_OK competencia=$competencia bytes=$bytes sha256=$sha"
echo "marker=$marker"
