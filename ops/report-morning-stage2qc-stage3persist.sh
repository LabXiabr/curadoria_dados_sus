#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "SUSLABX_MORNING_REPORT timestamp=$(date -Is)"
echo "git_commit=$(git -C "$ROOT" rev-parse HEAD)"
echo

bash "$ROOT/ops/status-morning-stage2qc-stage3persist.sh" || true

echo
echo "=== STAGE2 MARKERS ==="
for f in   "$LAKE_ROOT/state/sih/qc_bronze_modern_current.ok"   "$LAKE_ROOT/state/sih/qc_dimensions_current.ok"   "$LAKE_ROOT/state/stage2_postqc/stage2_postqc_current.ok"   "$LAKE_ROOT/state/stage2_postqc/stage2_semantic_current.ok"; do
  if [[ -f "$f" ]]; then
    echo "--- $f"; cat "$f"
  else
    echo "MISSING $f"
  fi
done

echo
echo "=== STAGE3 MARKER ==="
f="$LAKE_ROOT/state/stage3_persist/stage3_sia_sql_present_current.ok"
if [[ -f "$f" ]]; then
  cat "$f"
else
  echo "MISSING $f"
fi

echo
echo "=== SIA STATUS ==="
python3 "$ROOT/ops/status-migration.py" --lake-root "$LAKE_ROOT" --system SIA || true

echo
echo "=== TABNET QC SUMMARY ==="
tabrun=""
if [[ -f "$LAKE_ROOT/state/stage2_postqc/current.status" ]]; then
  tabrun="$(awk -F= '$1=="run"{sub(/^run=/,"");print;exit}' "$LAKE_ROOT/state/stage2_postqc/current.status")"
fi
tabcsv="$tabrun/qc_tabnet_aih_aprovadas.csv"
if [[ -n "$tabrun" && -f "$tabcsv" ]]; then
  python3 - "$tabcsv" <<'PY'
import csv,collections,sys
p=sys.argv[1]
with open(p,encoding="utf-8",newline="") as f:
    rows=list(csv.DictReader(f))
c=collections.Counter(r.get("status","") for r in rows)
print(f"pairs={len(rows)}")
for k in sorted(c):
    print(f"{k}={c[k]}")
PY
else
  echo "tabnet_qc=absent"
fi

echo
echo "=== LATEST DIMENSION QC ==="
q="$(ls -1t "$LAKE_ROOT"/state/sih/qc_dimensions_*.csv 2>/dev/null | head -1 || true)"
if [[ -n "$q" ]]; then
  cat "$q"
else
  echo "dimension_qc=absent"
fi

echo
echo "=== DIMENSION MARKER ==="
if [[ -f "$LAKE_ROOT/state/sih/qc_dimensions_current.ok" ]]; then
  cat "$LAKE_ROOT/state/sih/qc_dimensions_current.ok"
else
  echo "dimension_marker=absent"
fi

echo
echo "=== DISK ==="
df -h "$LAKE_ROOT"
echo "SUSLABX_MORNING_REPORT_END"
