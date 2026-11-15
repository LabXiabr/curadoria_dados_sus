#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
FTP_BASE="${SIGTAP_FTP_BASE:-ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads}"

RAW="$LAKE_ROOT/raw/sigtap/zip"
BRONZE="$LAKE_ROOT/bronze/sigtap"
STATE="$LAKE_ROOT/state/sigtap"

for c in curl sed sort find awk comm wc grep; do
    command -v "$c" >/dev/null 2>&1 || {
        echo "ERRO: comando ausente: $c" >&2
        exit 2
    }
done

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

ftp_names="$tmp/ftp_names"
canonical="$tmp/canonical.tsv"
ftp_comp="$tmp/ftp_comp"
raw_comp="$tmp/raw_comp"
bronze_comp="$tmp/bronze_comp"
qc_comp="$tmp/qc_comp"
marker_mismatch="$tmp/marker_mismatch"

curl -fsS --list-only "$FTP_BASE/"     | tr -d '\r'     | grep -E '^TabelaUnificada_[0-9]{6}.*\.zip$'     | sort -u > "$ftp_names"

sed -nE 's/^(TabelaUnificada_([0-9]{6}).*\.zip)$/\2\t\1/p' "$ftp_names"     | sort -t $'\t' -k1,1 -k2,2     | awk -F'\t' '{best[$1]=$2} END {for (c in best) print c "\t" best[c]}'     | sort -k1,1 > "$canonical"

cut -f1 "$canonical" > "$ftp_comp"

find "$RAW" -maxdepth 1 -type f -name 'TabelaUnificada_*.zip' -printf '%f\n'     | sed -nE 's/^TabelaUnificada_([0-9]{6}).*\.zip$/\1/p'     | sort -u > "$raw_comp"

find "$BRONZE/tb_procedimento"     -mindepth 1 -maxdepth 1 -type d -name 'competencia=*' -printf '%f\n' 2>/dev/null     | sed 's/^competencia=//'     | sort -u > "$bronze_comp"

find "$STATE"     -maxdepth 1 -type f -name 'qc_raw_bronze_??????.ok' -printf '%f\n'     | sed -nE 's/^qc_raw_bronze_([0-9]{6})\.ok$/\1/p'     | sort -u > "$qc_comp"

: > "$marker_mismatch"
while IFS=$'\t' read -r comp expected_zip; do
    marker="$STATE/qc_raw_bronze_${comp}.ok"
    [[ -f "$marker" ]] || continue
    actual_zip="$(sed -n 's/^zip=//p' "$marker" | head -1)"
    if [[ "$actual_zip" != "$expected_zip" ]]; then
        printf '%s\t%s\t%s\n' "$comp" "$expected_zip" "$actual_zip" >> "$marker_mismatch"
    fi
done < "$canonical"

printf '%-10s %s\n' ftp "$(wc -l < "$ftp_comp")"
printf '%-10s %s\n' raw "$(wc -l < "$raw_comp")"
printf '%-10s %s\n' bronze "$(wc -l < "$bronze_comp")"
printf '%-10s %s\n' qc "$(wc -l < "$qc_comp")"

echo
echo "=== FALTAM NO RAW ==="
comm -23 "$ftp_comp" "$raw_comp" || true
echo
echo "=== FALTAM NA BRONZE ==="
comm -23 "$ftp_comp" "$bronze_comp" || true
echo
echo "=== FALTAM NO QC ==="
comm -23 "$ftp_comp" "$qc_comp" || true
echo
echo "=== MARKERS COM ZIP DIVERGENTE DO CANONICO FTP ==="
cat "$marker_mismatch"

missing_raw="$(comm -23 "$ftp_comp" "$raw_comp" | wc -l)"
missing_bronze="$(comm -23 "$ftp_comp" "$bronze_comp" | wc -l)"
missing_qc="$(comm -23 "$ftp_comp" "$qc_comp" | wc -l)"
mismatch="$(wc -l < "$marker_mismatch")"

if (( missing_raw || missing_bronze || missing_qc || mismatch )); then
    echo
    echo "SIGTAP_BRONZE_GLOBAL_QC_FAIL raw=$missing_raw bronze=$missing_bronze qc=$missing_qc marker_zip=$mismatch" >&2
    exit 20
fi

marker="$STATE/bronze_global_qc.ok"
{
    echo "timestamp=$(date -Is)"
    echo "competencias=$(wc -l < "$ftp_comp")"
    echo "source=$FTP_BASE"
    echo "gate=ftp_raw_bronze_qc_marker_zip"
} > "$marker"

echo
echo "SIGTAP_BRONZE_GLOBAL_QC_OK $marker"
