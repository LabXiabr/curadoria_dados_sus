#!/usr/bin/env bash
set -Eeuo pipefail

OLD_ROOT="${OLD_ROOT:-/dados/abertos/suslake}"
NEW_ROOT="${NEW_ROOT:-/dados/abertos/suslabx}"
MODE="dry-run"
FORCE=0
COMPAT_SYMLINK=0

usage() {
  cat <<'EOF'
Uso:
  rename-suslake-to-suslabx.sh [--execute] [--force] [--compat-symlink]

Padrao: dry-run.
Variaveis:
  OLD_ROOT=/dados/abertos/suslake
  NEW_ROOT=/dados/abertos/suslabx

O script:
  1. bloqueia a renomeacao se detectar execucao ativa usando OLD_ROOT;
  2. verifica overnight SIH sem OVERNIGHT_DONE;
  3. exige origem existente e destino ausente;
  4. renomeia a raiz no mesmo filesystem;
  5. procura referencias residuais em configuracoes e informa o que precisa ajuste;
  6. opcionalmente cria symlink temporario suslake -> suslabx.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) MODE="execute"; shift ;;
    --force) FORCE=1; shift ;;
    --compat-symlink) COMPAT_SYMLINK=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Parametro desconhecido: $1" >&2; usage; exit 2 ;;
  esac
done

log(){ printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
die(){ log "ERRO: $*"; exit 1; }

[[ "$OLD_ROOT" != "$NEW_ROOT" ]] || die "OLD_ROOT e NEW_ROOT sao iguais"
[[ -d "$OLD_ROOT" ]] || die "origem inexistente: $OLD_ROOT"
[[ ! -e "$NEW_ROOT" ]] || die "destino ja existe: $NEW_ROOT"

old_parent="$(dirname "$OLD_ROOT")"
new_parent="$(dirname "$NEW_ROOT")"
old_dev="$(stat -c '%d' "$old_parent")"
new_dev="$(stat -c '%d' "$new_parent")"
[[ "$old_dev" == "$new_dev" ]] || die "origem/destino nao estao no mesmo filesystem"

active=""
if command -v pgrep >/dev/null 2>&1; then
  active="$(pgrep -af -- "$OLD_ROOT" 2>/dev/null | grep -v -F "$0" || true)"
fi
if [[ -n "$active" && "$FORCE" != "1" ]]; then
  printf '%s\n' "$active" >&2
  die "processo(s) ainda referenciam $OLD_ROOT; use --force somente apos conferir"
fi

unfinished=""
if [[ -d "$OLD_ROOT/state/overnight" ]]; then
  while IFS= read -r logf; do
    [[ -f "$logf" ]] || continue
    if ! grep -qx 'OVERNIGHT_DONE' "$logf"; then
      unfinished+="$logf"$'\n'
    fi
  done < <(find "$OLD_ROOT/state/overnight" -mindepth 2 -maxdepth 2 -type f -name main.log -print 2>/dev/null)
fi
if [[ -n "$unfinished" && "$FORCE" != "1" ]]; then
  printf 'Overnight(s) sem OVERNIGHT_DONE:\n%s' "$unfinished" >&2
  die "renomeacao bloqueada enquanto houver job potencialmente ativo/incompleto"
fi

log "Plano: $OLD_ROOT -> $NEW_ROOT"
log "Filesystem: device=$old_dev"
log "Modo: $MODE"

if [[ "$MODE" != "execute" ]]; then
  log "DRY_RUN: nenhuma alteracao realizada"
  exit 0
fi

mv -- "$OLD_ROOT" "$NEW_ROOT"
log "Raiz renomeada"

if [[ "$COMPAT_SYMLINK" == "1" ]]; then
  ln -s -- "$NEW_ROOT" "$OLD_ROOT"
  log "Symlink temporario criado: $OLD_ROOT -> $NEW_ROOT"
fi

log "Referencias residuais conhecidas fora da arvore de dados (somente relatorio):"
for root in /etc/apache2 /etc/systemd/system /etc/cron.d /etc/cron.daily /etc/cron.hourly "$HOME"; do
  [[ -e "$root" ]] || continue
  grep -RIl --exclude-dir=.git --exclude='*.parquet' --exclude='*.dbc' -- "$OLD_ROOT" "$root" 2>/dev/null | head -100 || true
done

log "OK: raiz atual=$NEW_ROOT"
log "Depois de ajustar Apache/systemd/cron, valide e remova eventual symlink de compatibilidade."
