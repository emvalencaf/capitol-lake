#!/usr/bin/env bash
# Turn the per-session usage log on or off, or show its state.
#   scripts/usage-tracking.sh on|off|status
set -euo pipefail
root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
conf="$root/.claude/usage.conf"

state() { grep -E '^USAGE_LOG=' "$conf" 2>/dev/null | tail -1 | cut -d= -f2 || echo off; }

case "${1:-status}" in
  on | off)
    mkdir -p "$(dirname "$conf")"
    cat >"$conf" <<CONF
# Per-session usage log. Managed by scripts/usage-tracking.sh.
# on: the status line records one small JSON file per session in .claude/usage/
# off: nothing is recorded.
USAGE_LOG=$1
CONF
    echo "usage tracking: $1"
    ;;
  status) echo "usage tracking: $(state || true)" ;;
  *) sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
