#!/usr/bin/env bash
set -Eeuo pipefail

LAKE_ROOT="${LAKE_ROOT:-/dados/abertos/suslabx}"
LOGROOT="$LAKE_ROOT/logs/dissemin"
STATER="$LAKE_ROOT/state/dissemin"

SRC_HOME="${SRC_HOME:-/home/ferre/Downloads/dbc}"
SRC_SDB="${SRC_SDB:-/mnt/sdb/bdsus/dbc}"

DST_HOME="$LAKE_ROOT/raw/dissemin/dbc/_legacy/from_home"
DST_SDB="$LAKE_ROOT/raw/dissemin/dbc/_legacy/from_sdb"

mkdir -p "$LOGROOT" "$STATER" "$DST_HOME" "$DST_SDB"

exec_one() {
    local src="$1" dst="$2" tag="$3"
    local ts log manifest remaining

    [[ -d "$src" ]] || {
        echo "SKIP: $src ausente"
        return 0
    }

    ts="$(date +%Y%m%d_%H%M%S)"
    log="$LOGROOT/migrate_${tag}_${ts}.log"
    manifest="$STATER/${tag}_sha256_${ts}.txt"

    echo "=== $tag ===" | tee -a "$log"
    du -sh "$src" | tee -a "$log"
    df -h "$src" "$dst" | tee -a "$log"

    rsync \
        -a \
        --checksum \
        --partial \
        --remove-source-files \
        --info=progress2 \
        "$src/" "$dst/" 2>&1 | tee -a "$log"

    remaining="$(find "$src" -type f | wc -l)"
    if (( remaining != 0 )); then
        echo "ERRO: restaram $remaining arquivos em $src" | tee -a "$log" >&2
        exit 30
    fi

    find "$src" -depth -type d -empty -delete 2>/dev/null || true

    echo "Gerando SHA-256 do destino..." | tee -a "$log"
    (
        cd "$dst"
        find . -type f -print0 \
            | sort -z \
            | xargs -0 -r sha256sum
    ) > "$manifest"

    echo "OK $tag" | tee -a "$log"
    echo "manifest=$manifest" | tee -a "$log"
    du -sh "$dst" | tee -a "$log"
}

echo "Inicio $(date -Is)"
echo "Primeiro /home para liberar filesystem em 100%."
exec_one "$SRC_HOME" "$DST_HOME" "dbc_from_home"
exec_one "$SRC_SDB" "$DST_SDB" "dbc_from_sdb"
echo "Fim $(date -Is)"
