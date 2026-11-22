#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "SUSLABX_OVERNIGHT_REPORT timestamp=$(date -Is)"
echo "git_commit=$(git -C "$ROOT" rev-parse HEAD)"
echo

echo "######## STAGE 2 ########"
bash "$ROOT/ops/status-stage2-sih-modern.sh" || true

echo
echo "######## STAGE 3 ########"
bash "$ROOT/ops/status-stage3-sia-modern.sh" || true

echo
echo "######## SIH MIGRATION STATUS ########"
python3 "$ROOT/ops/status-migration.py" --lake-root "$LAKE_ROOT" --system SIH --details || true

echo
echo "######## SIA MIGRATION STATUS ########"
python3 "$ROOT/ops/status-migration.py" --lake-root "$LAKE_ROOT" --system SIA --details || true

echo
echo "######## MARKERS ########"
for f in   "$LAKE_ROOT/state/stage2/stage2_sih_modern_current.ok"   "$LAKE_ROOT/state/sih/qc_bronze_modern_current.ok"   "$LAKE_ROOT/state/sih/qc_tabnet_aih_current.ok"   "$LAKE_ROOT/state/stage3/stage3_sia_modern_pa_current.ok"   "$LAKE_ROOT/state/sia/qc_source_staging_live_current.ok"; do
  if [[ -f "$f" ]]; then
    echo "--- $f"
    cat "$f"
  else
    echo "MISSING $f"
  fi
done

echo
echo "######## DISK ########"
df -h "$LAKE_ROOT"

echo
echo "SUSLABX_OVERNIGHT_REPORT_END"
