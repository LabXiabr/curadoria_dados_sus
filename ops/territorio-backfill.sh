#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FTP_ROOT="${TERRITORIO_FTP_ROOT:-ftp://ftp.datasus.gov.br/territorio/tabelas}"
LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslake}"
FROM_YEAR=""
TO_YEAR=""

usage() {
  cat <<'USAGE'
Uso:
  ops/territorio-backfill.sh [--from-year AAAA] [--to-year AAAA]

Descobre todos os snapshots territoriais publicados no FTP no intervalo,
preserva o ZIP no Raw e gera Bronze por snapshot. Nao regride a Silver current.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-year) FROM_YEAR="$2"; shift 2 ;;
    --to-year) TO_YEAR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
  esac
done

for c in curl grep sed sort awk python3; do
  command -v "$c" >/dev/null 2>&1 || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done

years="$(mktemp)"
trap 'rm -f "$years"' EXIT

curl -fsS --list-only "$FTP_ROOT/"   | tr -d '\r'   | sed 's:/*$::'   | grep -E '^[0-9]{4}$'   | sort -u > "$years"

[[ -s "$years" ]] || { echo "ERRO: nenhum diretorio anual encontrado em $FTP_ROOT/" >&2; exit 4; }

[[ -n "$FROM_YEAR" ]] || FROM_YEAR="$(head -1 "$years")"
[[ -n "$TO_YEAR" ]] || TO_YEAR="$(tail -1 "$years")"

[[ "$FROM_YEAR" =~ ^[0-9]{4}$ && "$TO_YEAR" =~ ^[0-9]{4}$ ]] || {
  echo "ERRO: intervalo anual invalido" >&2
  exit 2
}

report="$LAKE_ROOT/state/reference/territorio_backfill_$(date +%Y%m%d_%H%M%S).tsv"
mkdir -p "$(dirname "$report")"
printf 'snapshot\tyear\tzip\tstatus\n' > "$report"

fail=0
while IFS= read -r year; do
  (( year < FROM_YEAR || year > TO_YEAR )) && continue

  listing="$(mktemp)"
  if ! curl -fsS --list-only "$FTP_ROOT/$year/" | tr -d '\r' > "$listing"; then
    echo "WARN: nao foi possivel listar $year" >&2
    rm -f "$listing"
    continue
  fi

  while IFS=$'\t' read -r snapshot zipname; do
    [[ -n "$snapshot" && -n "$zipname" ]] || continue
    echo "=== TERRITORIO $snapshot $zipname ==="

    if ! "$ROOT/ops/territorio-acquire.sh" --year "$year" --zip-name "$zipname"; then
      printf '%s\t%s\t%s\tfailed_acquire\n' "$snapshot" "$year" "$zipname" >> "$report"
      ((fail+=1))
      continue
    fi

    marker="$LAKE_ROOT/state/reference/territorio_${snapshot}.raw.ok"
    if [[ ! -f "$marker" ]]; then
      printf '%s\t%s\t%s\tmissing_marker\n' "$snapshot" "$year" "$zipname" >> "$report"
      ((fail+=1))
      continue
    fi
    zpath="$(sed -n 's/^path=//p' "$marker" | head -1)"

    if python3 "$ROOT/etl/parquet_duckdb/reference/build_territorio.py"         --zip "$zpath" --snapshot "$snapshot"; then
      printf '%s\t%s\t%s\tok\n' "$snapshot" "$year" "$zipname" >> "$report"
    else
      printf '%s\t%s\t%s\tfailed_build\n' "$snapshot" "$year" "$zipname" >> "$report"
      ((fail+=1))
    fi
  done < <(
    sed -nE 's/^([0-9]{2})[-_].*base[_-]?territorial.*\.zip$/\1\t&/Ip' "$listing"       | awk -F'\t' -v y="$year" '
          {
            snap=y $1
            best[snap]=$2
          }
          END {
            for (s in best) print s "\t" best[s]
          }'       | sort -k1,1
  )

  rm -f "$listing"
done < "$years"

echo "Relatorio: $report"
if (( fail )); then
  rm -f "$LAKE_ROOT/state/reference/territorio_backfill_complete.ok"
  echo "TERRITORIO_BACKFILL_INCOMPLETO falhas=$fail" >&2
  exit 20
fi

ok_count="$(awk -F'\t' 'NR>1 && $4=="ok"{n++} END{print n+0}' "$report")"
first_snapshot="$(awk -F'\t' 'NR>1 && $4=="ok"{print $1}' "$report" | sort | head -1)"
last_snapshot="$(awk -F'\t' 'NR>1 && $4=="ok"{print $1}' "$report" | sort | tail -1)"
marker="$LAKE_ROOT/state/reference/territorio_backfill_complete.ok"
{
  echo "timestamp=$(date -Is)"
  echo "from_year=$FROM_YEAR"
  echo "to_year=$TO_YEAR"
  echo "snapshots_ok=$ok_count"
  echo "first_snapshot=$first_snapshot"
  echo "last_snapshot=$last_snapshot"
  echo "report=$report"
} > "$marker"

echo "TERRITORIO_BACKFILL_OK from=$FROM_YEAR to=$TO_YEAR snapshots=$ok_count"
echo "marker=$marker"
