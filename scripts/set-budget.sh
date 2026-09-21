#!/usr/bin/env bash
# Set the USD budget shown by the status line when you pay per token
# (no subscription rate limits). Takes effect on the next status line refresh.
#
#   scripts/set-budget.sh 50            this project only (.claude/budget, git-ignored)
#   scripts/set-budget.sh 50 --global   every project (~/.claude/budget)
#   scripts/set-budget.sh --show        print the budget in effect and where it comes from
#   scripts/set-budget.sh --clear       remove the project budget (--global: the global one)
#
# Precedence, highest first: CLAUDE_BUDGET_USD, project file, global file, 100.
set -euo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
project_file="$root/.claude/budget"
global_file="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/budget"

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

amount="" scope="project" action="set"
for arg in "$@"; do
  case "$arg" in
    --global) scope="global" ;;
    --show) action="show" ;;
    --clear) action="clear" ;;
    -h | --help) usage ;;
    -*) echo "unknown option: $arg" >&2; usage 1 ;;
    *) amount="$arg" ;;
  esac
done

file="$project_file"
[[ "$scope" == "global" ]] && file="$global_file"

read_budget() { [[ -f "$1" ]] && tr -d '[:space:]' <"$1" || true; }

case "$action" in
  show)
    if [[ -n "${CLAUDE_BUDGET_USD:-}" ]]; then echo "\$ ${CLAUDE_BUDGET_USD} (env CLAUDE_BUDGET_USD)"
    elif [[ -n "$(read_budget "$project_file")" ]]; then echo "\$ $(read_budget "$project_file") ($project_file)"
    elif [[ -n "$(read_budget "$global_file")" ]]; then echo "\$ $(read_budget "$global_file") ($global_file)"
    else echo "\$ 100 (default)"; fi
    ;;
  clear)
    rm -f "$file"
    echo "removed $file"
    ;;
  set)
    [[ -z "$amount" ]] && usage 1
    if ! [[ "$amount" =~ ^[0-9]+([.][0-9]+)?$ ]] || ! awk -v a="$amount" 'BEGIN{exit !(a > 0)}'; then
      echo "budget must be a positive number in USD, got: $amount" >&2
      exit 1
    fi
    mkdir -p "$(dirname "$file")"
    echo "$amount" >"$file"
    echo "budget set to \$ $amount ($file)"
    ;;
esac
