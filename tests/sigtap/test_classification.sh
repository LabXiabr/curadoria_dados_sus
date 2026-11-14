#!/usr/bin/env bash
set -Eeuo pipefail
classify(){
  local table="$1" rows="$2" has_layout="$3" width_ok="$4"
  case "$table" in
    layout|leia_me|*_layout) echo ignored_metadata; return ;;
  esac
  [[ "$has_layout" == 1 ]] || { echo unknown_layout; return; }
  [[ "$rows" == 0 ]] && { echo ok; return; }
  [[ "$width_ok" == 1 ]] && echo ok || echo width_mismatch
}
[[ "$(classify tb_cid 10 1 1)" == ok ]]
[[ "$(classify rl_procedimento_tuss 0 1 0)" == ok ]]
[[ "$(classify tb_cid_layout 7 0 0)" == ignored_metadata ]]
[[ "$(classify leia_me 303 0 0)" == ignored_metadata ]]
[[ "$(classify layout 274 0 0)" == ignored_metadata ]]
[[ "$(classify tabela_nova 1 0 1)" == unknown_layout ]]
echo "OK classification"
