#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 -m py_compile "$ROOT/etl/psql/dissemin/enrich_sia_pa_cnspcn.py"
python3 "$ROOT/etl/psql/dissemin/enrich_sia_pa_cnspcn.py" "$@"
