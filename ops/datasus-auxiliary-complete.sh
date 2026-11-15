#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 -m py_compile   "$ROOT/ops/acquire-datasus-auxiliary.py"   "$ROOT/ops/inventory-datasus-auxiliary.py"

"$ROOT/ops/acquire-datasus-auxiliary.py" "$@"
"$ROOT/ops/inventory-datasus-auxiliary.py"

echo "DATASUS_AUX_COMPLETE_OK"
