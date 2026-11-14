#!/usr/bin/env bash
set -Eeuo pipefail
HOST="${BURETA_HOST:-192.168.88.12}"
ssh "$HOST" '
  echo "=== FILESYSTEMS ==="
  df -h /dados/abertos /mnt/sdb /home /var
  echo
  echo "=== DBC LEGADOS ==="
  du -sh /mnt/sdb/bdsus/dbc 2>/dev/null || true
  du -sh /home/ferre/Downloads/dbc 2>/dev/null || true
'
