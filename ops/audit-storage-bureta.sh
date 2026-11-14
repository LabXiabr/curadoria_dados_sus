#!/usr/bin/env bash
set -Eeuo pipefail
JUMP="${BURETA_SSH_JUMP:-ferre@ssh.labx.ia.br}"
TARGET="${BURETA_SSH_TARGET:-ferre@bureta}"
ssh -J "$JUMP" "$TARGET" '
  echo "=== FILESYSTEMS ==="
  df -h /dados/abertos /mnt/sdb /home /var
  echo
  echo "=== DBC LEGADOS ==="
  du -sh /mnt/sdb/bdsus/dbc 2>/dev/null || true
  du -sh /home/ferre/Downloads/dbc 2>/dev/null || true
'
