#!/usr/bin/env bash
# Record the status line's per-session numbers in .claude/usage/<session_id>.json.
# Reads the status line JSON on stdin; called by scripts/statusline.sh when
# USAGE_LOG=on in .claude/usage.conf. Numbers and metadata only: no prompts,
# no conversation content. The cost is Claude Code's own estimate.
# Requires: jq, git.
set -euo pipefail

input="$(cat)"
root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
sid="$(jq -r '.session_id // empty' <<<"$input" 2>/dev/null || true)"
[[ "$sid" =~ ^[A-Za-z0-9_-]+$ ]] || exit 0

dir="$root/.claude/usage"
file="$dir/$sid.json"
mkdir -p "$dir"

cwd="$(jq -r '.workspace.current_dir // .cwd // empty' <<<"$input")"
branch="$(git -C "${cwd:-$root}" branch --show-current 2>/dev/null || true)"
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
old='{}'
[[ -f "$file" ]] && old="$(cat "$file")"

new="$(jq -n --argjson in "$input" --argjson old "$old" \
  --arg project "$(basename "$root")" --arg branch "$branch" --arg now "$now" '
  ($in.context_window.used_percentage // 0) as $pct
  | {
      session_id: $in.session_id,
      project: $project,
      branch: $branch,
      model_id: ($in.model.id // null),
      model: ($in.model.display_name // null),
      effort: ($in.effort.level // null),
      first_seen: ($old.first_seen // $now),
      last_update: $now,
      duration_ms: ($in.cost.total_duration_ms // 0),
      cost_usd_estimated: ($in.cost.total_cost_usd // 0),
      lines_added: ($in.cost.total_lines_added // 0),
      lines_removed: ($in.cost.total_lines_removed // 0),
      context_size: ($in.context_window.context_window_size // null),
      context_pct: $pct,
      context_peak_pct: ([$pct, ($old.context_peak_pct // 0)] | max),
      tokens_in: ($in.context_window.total_input_tokens // 0),
      tokens_out: ($in.context_window.total_output_tokens // 0)
    }')"

# Skip the write when nothing but the timestamp changed.
if [[ -f "$file" ]] && [[ "$(jq -S 'del(.last_update)' <<<"$new")" == "$(jq -S 'del(.last_update)' <<<"$old")" ]]; then
  exit 0
fi

tmp="$(mktemp "$dir/.tmp.XXXXXX")"
printf '%s\n' "$new" >"$tmp"
mv "$tmp" "$file"
