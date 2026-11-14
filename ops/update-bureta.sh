#!/usr/bin/env bash
set -Eeuo pipefail
BRANCH="${1:-main}"
HOST="${BURETA_HOST:-192.168.88.12}"
REPO="${BURETA_REPO:-/dados/abertos/repos/curadoria_dados_sus}"

case "$BRANCH" in
  main|develop) ;;
  *) echo "Branch permitida: main ou develop" >&2; exit 2 ;;
esac

ssh "$HOST" "
  set -Eeuo pipefail
  cd '$REPO'
  test -z \"\$(git status --porcelain)\" || {
    echo 'ERRO: clone da bureta possui alterações locais' >&2
    exit 3
  }
  git fetch --prune origin
  git switch '$BRANCH'
  git pull --ff-only origin '$BRANCH'
  printf 'bureta branch='
  git branch --show-current
  printf 'commit='
  git rev-parse --short HEAD
"
