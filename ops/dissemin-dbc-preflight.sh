#!/usr/bin/env bash
set -Eeuo pipefail

for c in python3 duckdb Rscript; do
  command -v "$c" >/dev/null || { echo "ERRO: comando ausente: $c" >&2; exit 3; }
done

Rscript -e 'if (!requireNamespace("microdatasus", quietly=TRUE)) quit(status=42)' || {
  rc=$?
  if [[ $rc -eq 42 ]]; then
    echo "ERRO: pacote R microdatasus ausente" >&2
  else
    echo "ERRO: falha no preflight R/microdatasus rc=$rc" >&2
  fi
  exit "$rc"
}

echo "DISSEMIN_DBC_PREFLIGHT_OK"
