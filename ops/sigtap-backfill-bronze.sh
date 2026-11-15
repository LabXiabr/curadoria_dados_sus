#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/etl/parquet_duckdb/sigtap/run.sh"
QC="$ROOT/ops/qc-sigtap-raw-bronze.sh"

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
FTP_BASE="${SIGTAP_FTP_BASE:-ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads}"
RAW="$LAKE_ROOT/raw/sigtap/zip"
STATE="$LAKE_ROOT/state/sigtap"
LOGROOT="$LAKE_ROOT/logs/sigtap"

FROM="000000"
TO="999999"
REFRESH_REMOTE=1

usage() {
    cat <<'USAGE'
Uso:
  ops/sigtap-backfill-bronze.sh [--from YYYYMM] [--to YYYYMM] [--local-only]

Completa a Bronze SIGTAP por competencia usando a versao canonica mais recente
(nome de ZIP mais alto) conhecida no Raw local + listagem FTP oficial.
Para cada competencia: gera Bronze, executa QC independente Raw->Bronze e grava marker.
Competencias ja homologadas com o mesmo ZIP canonico sao retomadas/idempotentes.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) FROM="$2"; shift 2 ;;
        --to) TO="$2"; shift 2 ;;
        --local-only) REFRESH_REMOTE=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
    esac
done

[[ "$FROM" =~ ^[0-9]{6}$ ]] || { echo "--from invalido: $FROM" >&2; exit 2; }
[[ "$TO" =~ ^[0-9]{6}$ ]] || { echo "--to invalido: $TO" >&2; exit 2; }

for c in bash curl unzip sha256sum awk sed sort find; do
    command -v "$c" >/dev/null 2>&1 || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done
[[ -x "$RUN" ]] || { echo "ERRO: $RUN ausente/nao executavel" >&2; exit 3; }
[[ -x "$QC" ]] || { echo "ERRO: $QC ausente/nao executavel" >&2; exit 3; }

mkdir -p "$RAW" "$STATE" "$LOGROOT"
ts="$(date +%Y%m%d_%H%M%S)_$$"
log="$LOGROOT/backfill_bronze_${ts}.log"
exec > >(tee -a "$log") 2>&1

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
local_names="$work/local.txt"
remote_names="$work/remote.txt"
all_names="$work/all.txt"
canon="$work/canonical.tsv"

find "$RAW" -maxdepth 1 -type f -name 'TabelaUnificada_[0-9][0-9][0-9][0-9][0-9][0-9]*.zip' -printf '%f\n' \
    | sort -u > "$local_names"
: > "$remote_names"

if (( REFRESH_REMOTE == 1 )); then
    echo "Consultando FTP oficial uma vez: $FTP_BASE"
    if curl --fail --silent --show-error --list-only "$FTP_BASE/" \
        | tr -d '\r' \
        | grep -E '^TabelaUnificada_[0-9]{6}.*\.zip$' \
        | sort -u > "$remote_names"; then
        echo "FTP_OK nomes=$(wc -l < "$remote_names")"
    else
        echo "AVISO: FTP indisponivel; prosseguindo com Raw local." >&2
        : > "$remote_names"
    fi
fi

cat "$local_names" "$remote_names" | sort -u > "$all_names"

sed -nE 's/^(TabelaUnificada_([0-9]{6}).*\.zip)$/\2\t\1/p' "$all_names" \
    | sort -t $'\t' -k1,1 -k2,2 \
    | awk -F'\t' '{best[$1]=$2} END {for (c in best) print c "\t" best[c]}' \
    | sort -k1,1 > "$canon"

awk -F'\t' -v a="$FROM" -v b="$TO" '$1>=a && $1<=b' "$canon" > "$canon.filtered"
mv "$canon.filtered" "$canon"

n_target="$(wc -l < "$canon")"
(( n_target > 0 )) || { echo "ERRO: nenhuma competencia encontrada." >&2; exit 4; }
echo "Competencias alvo: $n_target ($(head -1 "$canon" | cut -f1) .. $(tail -1 "$canon" | cut -f1))"

while IFS=$'\t' read -r comp zipname; do
    [[ -f "$RAW/$zipname" ]] && continue
    if grep -Fxq "$zipname" "$remote_names"; then
        echo "DOWNLOAD $comp $zipname"
        partial="$RAW/$zipname.partial.$$"
        rm -f "$partial"
        curl --fail --location --silent --show-error --retry 4 --retry-delay 3 \
            --remote-time --output "$partial" "$FTP_BASE/$zipname"
        unzip -tq "$partial" >/dev/null
        mv "$partial" "$RAW/$zipname"
    else
        echo "ERRO: ZIP canonico ausente localmente e nao disponivel no FTP: $zipname" >&2
        exit 5
    fi
done < "$canon"

ok=0
skip=0
fail=0
report="$STATE/bronze_backfill_${ts}.tsv"
printf 'competencia\tzip\tstatus\tmarker\n' > "$report"

while IFS=$'\t' read -r comp zipname; do
    marker="$STATE/qc_raw_bronze_${comp}.ok"
    marker_zip=""
    if [[ -f "$marker" ]]; then
        marker_zip="$(sed -n 's/^zip=//p' "$marker" | head -1)"
    fi

    if [[ "$marker_zip" == "$zipname" && -f "$LAKE_ROOT/bronze/sigtap/tb_procedimento/competencia=$comp/part-000.parquet" ]]; then
        echo "SKIP homologado $comp $zipname"
        printf '%s\t%s\t%s\t%s\n' "$comp" "$zipname" "already_qc_ok" "$marker" >> "$report"
        ((skip+=1))
        continue
    fi

    echo "=== BRONZE $comp $zipname ==="
    if SIGTAP_OFFLINE=1 "$RUN" --competencia "$comp" --offline && "$QC" "$comp"; then
        new_marker_zip="$(sed -n 's/^zip=//p' "$marker" | head -1 2>/dev/null || true)"
        if [[ "$new_marker_zip" != "$zipname" ]]; then
            echo "ERRO $comp: marker aponta $new_marker_zip, esperado $zipname" >&2
            printf '%s\t%s\t%s\t%s\n' "$comp" "$zipname" "marker_zip_mismatch" "$marker" >> "$report"
            ((fail+=1))
        else
            printf '%s\t%s\t%s\t%s\n' "$comp" "$zipname" "qc_ok" "$marker" >> "$report"
            ((ok+=1))
        fi
    else
        printf '%s\t%s\t%s\t%s\n' "$comp" "$zipname" "failed" "$marker" >> "$report"
        ((fail+=1))
    fi
done < "$canon"

echo
echo "Relatorio: $report"
echo "novas=$ok ja_homologadas=$skip falhas=$fail total=$n_target"

gate_fail=0
while IFS=$'\t' read -r comp zipname; do
    marker="$STATE/qc_raw_bronze_${comp}.ok"
    [[ -f "$marker" ]] || { echo "FALTA marker $comp" >&2; ((gate_fail+=1)); continue; }
    marker_zip="$(sed -n 's/^zip=//p' "$marker" | head -1)"
    [[ "$marker_zip" == "$zipname" ]] || { echo "FALTA rehomologar $comp: $marker_zip != $zipname" >&2; ((gate_fail+=1)); }
done < "$canon"

if (( fail > 0 || gate_fail > 0 )); then
    echo "BRONZE_INCOMPLETA falhas=$fail gate=$gate_fail" >&2
    exit 20
fi

{
    echo "timestamp=$(date -Is)"
    echo "from=$FROM"
    echo "to=$TO"
    echo "competencias=$n_target"
    echo "report=$report"
} > "$STATE/bronze_complete.ok"

echo "BRONZE_COMPLETE_OK $STATE/bronze_complete.ok"
