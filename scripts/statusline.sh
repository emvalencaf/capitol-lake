#!/usr/bin/env bash
# Claude Code status line. Requires: jq, git.
#
#   dir · model (effort) · branch* ↑a↓b [+added/-removed]
#   ctx: 42% (84k/200k) · cost: $ 0.40/$ 100.00 (0%) · 12m · 85ecceb1
#   5h: 12% - reset in 3h10m · 7d: 30% - reset in 4d2h      (subscription only)
#
# The short session id is the value CONTRIBUTING.md asks for in the Session-Id
# commit trailer. A red branch means you are on a protected/integration branch
# (master, main, development): cut a work branch first.
#
# Budget shown when there are no rate limits in the input (pay-per-token instead
# of a Claude subscription). Set it with scripts/set-budget.sh. Precedence:
# CLAUDE_BUDGET_USD, .claude/budget (project), ~/.claude/budget (global), 100.

if ! command -v jq >/dev/null 2>&1; then
  echo "statusline: jq is required"
  exit 0
fi

input="$(cat)"
now="$(date +%s)"
budget_from_file() { [[ -f "$1" ]] && tr -d '[:space:]' <"$1"; }
BUDGET_USD="${CLAUDE_BUDGET_USD:-}"
if [[ -z "$BUDGET_USD" ]]; then
  root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  BUDGET_USD="$(budget_from_file "$root/.claude/budget" || budget_from_file "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/budget" || true)"
fi
[[ "$BUDGET_USD" =~ ^[0-9]+([.][0-9]+)?$ ]] || BUDGET_USD=100

RESET=$'\033[0m'; BOLD=$'\033[1m'; DIM=$'\033[2m'
CYAN=$'\033[36m'; MAGENTA=$'\033[35m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
ORANGE=$'\033[38;5;208m'; RED=$'\033[31m'; GRAY=$'\033[90m'
SEP="${DIM} · ${RESET}"

fmt_secs() {
  local s=$1
  if [[ -z "$s" || "$s" -le 0 ]] 2>/dev/null; then echo "--"; return; fi
  local d=$((s / 86400)) h=$(((s % 86400) / 3600)) m=$(((s % 3600) / 60))
  if ((d > 0)); then echo "${d}d${h}h"
  elif ((h > 0)); then echo "${h}h${m}m"
  else echo "${m}m"; fi
}

fmt_tokens() {
  local t=${1:-0}
  if ((t < 1000)); then echo "$t"; else awk -v t="$t" 'BEGIN{printf "%.0fk", t/1000}'; fi
}

color_for_pct() {
  local p=$1
  if ((p < 50)); then echo "$GREEN"
  elif ((p < 80)); then echo "$YELLOW"
  elif ((p < 95)); then echo "$ORANGE"
  else echo "$RED"; fi
}

# One jq call for every field; @sh makes the output safe to eval.
eval "$(jq -r '
  @sh "MODEL=\(.model.display_name // "?")",
  @sh "EFFORT=\(.effort.level // "")",
  @sh "DIR=\(.workspace.current_dir // .cwd // "")",
  @sh "SESSION_ID=\(.session_id // "?")",
  @sh "COST=\(.cost.total_cost_usd // 0)",
  @sh "LINES_ADD=\(.cost.total_lines_added // 0)",
  @sh "LINES_DEL=\(.cost.total_lines_removed // 0)",
  @sh "DURATION_MS=\(.cost.total_duration_ms // 0)",
  @sh "CTX_PCT=\((.context_window.used_percentage // 0) | floor)",
  @sh "CTX_SIZE=\(.context_window.context_window_size // 200000)",
  @sh "CTX_IN=\(.context_window.total_input_tokens // 0)",
  @sh "CTX_OUT=\(.context_window.total_output_tokens // 0)",
  @sh "FIVE_PCT=\(.rate_limits.five_hour.used_percentage // "")",
  @sh "FIVE_RESET=\(.rate_limits.five_hour.resets_at // "")",
  @sh "WEEK_PCT=\(.rate_limits.seven_day.used_percentage // "")",
  @sh "WEEK_RESET=\(.rate_limits.seven_day.resets_at // "")"
' <<<"$input" 2>/dev/null)"

# Defaults for when jq failed (empty or invalid input).
MODEL="${MODEL:-?}" EFFORT="${EFFORT:-}" SESSION_ID="${SESSION_ID:-?}"
COST="${COST:-0}" LINES_ADD="${LINES_ADD:-0}" LINES_DEL="${LINES_DEL:-0}"
DURATION_MS="${DURATION_MS:-0}" CTX_PCT="${CTX_PCT:-0}" CTX_SIZE="${CTX_SIZE:-200000}"
CTX_IN="${CTX_IN:-0}" CTX_OUT="${CTX_OUT:-0}"
FIVE_PCT="${FIVE_PCT:-}" FIVE_RESET="${FIVE_RESET:-}"
WEEK_PCT="${WEEK_PCT:-}" WEEK_RESET="${WEEK_RESET:-}"
[[ -z "${DIR:-}" ]] && DIR="$PWD"
DIRNAME="$(basename "$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || echo "$DIR")")"

# ---------- Usage log (opt-in per project, see scripts/usage-tracking.sh) ----------
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if grep -qx 'USAGE_LOG=on' "$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || echo "$DIR")/.claude/usage.conf" 2>/dev/null; then
  ( printf '%s' "$input" | (cd "$DIR" && "$script_dir/usage_log.sh") ) >/dev/null 2>&1 &
fi

# ---------- Git state (cached for 5s per session) ----------
CACHE_FILE="${TMPDIR:-/tmp}/statusline-git-${SESSION_ID}"
mtime="$(stat -c %Y "$CACHE_FILE" 2>/dev/null || stat -f %m "$CACHE_FILE" 2>/dev/null || echo 0)"
if ((now - mtime > 5)); then
  if git -C "$DIR" rev-parse --git-dir >/dev/null 2>&1; then
    branch="$(git -C "$DIR" branch --show-current 2>/dev/null)"
    dirty=""
    [[ -n "$(git -C "$DIR" status --porcelain 2>/dev/null | head -1)" ]] && dirty="*"
    ahead=0 behind=0
    read -r ahead behind < <(git -C "$DIR" rev-list --left-right --count '@{upstream}...HEAD' 2>/dev/null | awk '{print $2, $1}')
    printf '%s\t%s\t%s\t%s\n' "$branch" "$dirty" "${ahead:-0}" "${behind:-0}" >"$CACHE_FILE"
  else
    : >"$CACHE_FILE"
  fi
fi
IFS=$'\t' read -r BRANCH DIRTY AHEAD BEHIND <"$CACHE_FILE" 2>/dev/null

# ---------- Parts ----------
MODEL_PART="${BOLD}${CYAN}${MODEL}${RESET}"
[[ -n "$EFFORT" ]] && MODEL_PART+="${DIM} (${EFFORT})${RESET}"

BRANCH_PART=""
if [[ -n "$BRANCH" ]]; then
  BCOLOR="$MAGENTA"
  [[ "$BRANCH" == "master" || "$BRANCH" == "main" || "$BRANCH" == "development" ]] && BCOLOR="$RED"
  BRANCH_PART="${BCOLOR}${BRANCH}${DIRTY}${RESET}"
  ((AHEAD > 0)) && BRANCH_PART+=" ${GREEN}↑${AHEAD}${RESET}"
  ((BEHIND > 0)) && BRANCH_PART+=" ${YELLOW}↓${BEHIND}${RESET}"
  BRANCH_PART+=" ${DIM}[${RESET}${GREEN}+${LINES_ADD}${RESET}${DIM}/${RESET}${RED}-${LINES_DEL}${RESET}${DIM}]${RESET}"
fi

CTX_USED_FMT="$(fmt_tokens $((CTX_IN + CTX_OUT)))"
CTX_PART="${DIM}ctx:${RESET} $(color_for_pct "$CTX_PCT")${CTX_PCT}%${RESET} ${DIM}(${CTX_USED_FMT}/$(fmt_tokens "$CTX_SIZE"))${RESET}"

COST_FMT="$(printf '$ %.2f' "$COST")"
DURATION_PART="${DIM}$(fmt_secs $((DURATION_MS / 1000)))${RESET}"
SESSION_PART="${GRAY}${SESSION_ID:0:8}${RESET}"

LINE1="${DIRNAME}${SEP}${MODEL_PART}"
[[ -n "$BRANCH_PART" ]] && LINE1+="${SEP}${BRANCH_PART}"

if [[ -n "$FIVE_PCT" || -n "$WEEK_PCT" ]]; then
  # Subscription: show cost plainly, and the rate limits on a third line.
  COST_PART="${DIM}cost:${RESET} ${YELLOW}${COST_FMT}${RESET}"
  LIMITS=()
  if [[ -n "$FIVE_PCT" ]]; then
    p="$(printf '%.0f' "$FIVE_PCT")"
    LIMITS+=("${DIM}5h:${RESET} $(color_for_pct "$p")${p}%${RESET} ${DIM}- reset in $(fmt_secs $((FIVE_RESET - now)))${RESET}")
  fi
  if [[ -n "$WEEK_PCT" ]]; then
    p="$(printf '%.0f' "$WEEK_PCT")"
    LIMITS+=("${DIM}7d:${RESET} $(color_for_pct "$p")${p}%${RESET} ${DIM}- reset in $(fmt_secs $((WEEK_RESET - now)))${RESET}")
  fi
  LINE3=""
  for part in "${LIMITS[@]}"; do LINE3+="${LINE3:+$SEP}$part"; done
else
  # Own budget: show spend against CLAUDE_BUDGET_USD.
  BUDGET_PCT="$(awk -v c="$COST" -v b="$BUDGET_USD" 'BEGIN{ if (b<=0) print 0; else {p=c/b*100; if (p>999) p=999; printf "%.0f", p} }')"
  COST_PART="${DIM}cost:${RESET} ${YELLOW}${COST_FMT}${RESET}${DIM}/${RESET}$(color_for_pct "$BUDGET_PCT")$(printf '$ %.2f' "$BUDGET_USD")${RESET} ${DIM}(${BUDGET_PCT}%)${RESET}"
  LINE3=""
fi

LINE2="${CTX_PART}${SEP}${COST_PART}${SEP}${DURATION_PART}${SEP}${SESSION_PART}"

printf '%s\n%s\n' "$LINE1" "$LINE2"
[[ -n "$LINE3" ]] && printf '%s\n' "$LINE3"
exit 0
