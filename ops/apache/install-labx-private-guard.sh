#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/ops/apache/labx-suslabx-private.conf"
PRIVATE="/etc/apache2/conf-available/labx-suslabx-private.conf"
VHOST="/etc/apache2/conf-available/labx-public-parquet.conf"
STAMP="$(date +%Y%m%d_%H%M%S)"

[[ $EUID -eq 0 ]] || {
  echo "ERRO: execute com sudo: sudo $0" >&2
  exit 2
}

[[ -f "$SRC" ]] || { echo "ERRO: fragmento ausente: $SRC" >&2; exit 3; }
[[ -f "$VHOST" ]] || { echo "ERRO: vhost ausente: $VHOST" >&2; exit 4; }

cp -a "$VHOST" "$VHOST.bak_private_${STAMP}"
cp "$SRC" "$PRIVATE"

# O fragmento deve pertencer ao vhost :8766, nao ao contexto global.
a2disconf labx-suslake-private >/dev/null 2>&1 || true
a2disconf labx-suslabx-private >/dev/null 2>&1 || true

python3 - "$VHOST" <<'PY'
from pathlib import Path
import sys

p=Path(sys.argv[1])
s=p.read_text(encoding="utf-8")
begin="# LABX_SUSLABX_PRIVATE_GUARD_BEGIN"
end="# LABX_SUSLABX_PRIVATE_GUARD_END"
old_begin="# LABX_SUSLAKE_PRIVATE_GUARD_BEGIN"
old_end="# LABX_SUSLAKE_PRIVATE_GUARD_END"
include="IncludeOptional /etc/apache2/conf-available/labx-suslabx-private.conf"
old_include="IncludeOptional /etc/apache2/conf-available/labx-suslake-private.conf"

for bmark, emark in ((begin,end),(old_begin,old_end)):
    if bmark in s and emark in s:
        a=s.index(bmark)
        b=s.index(emark,a)+len(emark)
        s=s[:a]+s[b:]
s=s.replace(include,"").replace(old_include,"")

idx=s.rfind("</VirtualHost>")
if idx < 0:
    raise SystemExit("ERRO: </VirtualHost> nao encontrado")

block=f"""
    {begin}
    {include}
    {end}
"""
s=s[:idx]+block+s[idx:]
p.write_text(s,encoding="utf-8")
PY

apache2ctl configtest
systemctl reload apache2

echo "LABX_PRIVATE_GUARD_INSTALLED"
echo "vhost=$VHOST"
echo "fragment=$PRIVATE"
echo "backup=$VHOST.bak_private_${STAMP}"
