---
name: usage-report
description: >-
  Build a local HTML dashboard of Claude Code usage for this project: tokens in
  and out per session, per day and per skill, session duration, model, effort,
  context peak, most used skills and heuristic intents, the specs, tickets and
  branches each piece of work spanned across sessions, the tools used, subagents
  (kept separate from their session), effort by type of work (feature, bug fix,
  refactor...), plus the cost estimate the status line logged. Use when asked
  for a usage, spend, token or cost report, "which skills do I use most", or "how much did that session cost".
  Read-only over transcripts; writes only the report file.
user-invocable: true
argument-hint: "[--all] [--since YYYY-MM-DD] [--top N] [--limit N] [--tracker auto|local|github] [--offline] [-o report.html]"
allowed-tools: Bash
---

# Usage report

Generate a self-contained HTML dashboard from the session transcripts in
`~/.claude/projects/` and the per-session log in `.claude/usage/`.

```bash
uv run "${CLAUDE_SKILL_DIR}/scripts/usage_report.py" $ARGUMENTS
```

Then tell the user where the file is (default `.claude/usage/report.html`, which
is git-ignored) and summarise the headline numbers. Do not paste transcript
content into the answer.

## Arguments

- `--all`: every project under `~/.claude/projects/`, not just this one.
- `--since YYYY-MM-DD`: ignore sessions that started earlier.
- `--top N`: rows in the skill and intent rankings. Default 10, cap 50.
- `--limit N`: rows in the sessions table, most recent first. Default 25, cap 200.
- `--tracker auto|local|github`: how to read a bare ticket number such as `/implement 42`. Default `auto`: taken from `docs/agents/issue-tracker.md`.
- `--offline`: never call `gh`. GitHub references stay as `#N`, without title or state.
- `-o PATH`: output file.

## What is measured, and how reliable it is

| Number | Source | Reliability |
|---|---|---|
| Tokens in / out | Transcript `usage` per assistant message, de-duplicated by message id. "In" is fresh input plus cache creation plus cache read. | Exact as recorded |
| Duration, model, effort | Transcript timestamps, message model, per-turn effort | Exact as recorded |
| Context peak | Largest per-message context in the transcript; the peak percentage comes from the usage log | Exact when logged |
| **Cost** | `.claude/usage/<session>.json`, written by the status line from Claude Code's own `total_cost_usd` | **Estimate**: computed client-side, not your invoice. Only sessions after usage tracking was enabled have one. |
| Tokens per skill | Assistant tokens from a skill call (or slash command) until the next user prompt | **Approximate**: work after the skill call is attributed to it, even if unrelated |
| Skill usage | `Skill` tool calls and slash commands | Exact count of what was recorded |
| Tools | `tool_use` names, result error flag, call-to-result time | Exact counts; time includes permission waits |
| Subagents | `subagents/agent-*.jsonl` and their `meta.json` | Exact as recorded; kept separate from the session |
| Type of work | Commit tags, branch prefix, labels, skill | Deterministic from those signals, but one type per work |
| Intent | The slash command the session opened with, else a keyword match on the first prompt | **Heuristic**, not what the user really meant. Prompt text is never stored in the report. |

The report states the estimate and heuristic caveats on the page itself. There
is no dollar conversion from tokens and no price table.

## Tabs

The page has four tabs (pure HTML and CSS, no scripts): **Overview** (totals, tokens per day,
skills, intents, tools), **Work** (specs, tickets and implementation), **By type**
(feature, bug fix, refactor... and their effort) and **Sessions**.

## Tools

Only tool names are tracked, never their inputs or outputs: calls, sessions using
each, errors (from the result's error flag) and time from the call to its result.
That time includes waiting for your permission. There is no token or cost figure per tool.

## Subagents

Subagent transcripts live in `<session>/subagents/agent-*.jsonl`. They are read
and shown as **separate rows marked "subagent"**, nested under the session that
spawned them, with their own agent type, model, tokens in and out, duration and
tools. **They are never added to the parent session's numbers**: the session
row, the day chart, the skill ranking and each work item keep main-session
totals, and subagent totals appear beside them, labelled separately. The prompt
sent to a subagent is never read into the report. The status line's cost is one
number per main session; it is not split by subagent, and whether Claude Code
includes subagents in it is unverified.

## Type of work

Each piece of work in the **Work** tab gets one type from the strongest signal:
1. the tags of its commits (`feat`, `fix`, `refactor`, `docs`, `test`, `perf`, `chore`/`ci`/`build`/`style`, `revert`), most frequent wins, ties go to the first in that order;
2. its branch prefix (`fix/...`);
3. GitHub labels (`bug`, `enhancement`, `documentation`...), when `gh` is available;
4. the skill that opened it (`diagnosing-bugs` is a bug fix, `improve-codebase-architecture` a refactor).

With none of these it is shown as "No type signal"; sessions not linked to any
work are listed as "No work link". The source of each type is shown next to it.
A work has a single type, so a feature with a fix in the middle counts as a feature.

## Work: specs, tickets and implementation

The dashboard has a **Work** section that follows a feature through the flow
(`/grill-with-docs` → `/to-spec` → `/to-tickets` → `/implement` per ticket →
`/tdd` → `/code-review`), even though `/clear` gives each step a new session id.
Each piece of work lists its references, its sessions in order with the stage
each ran, tokens per session and in total, and the commits.

Sessions are joined when they share any of:

| Link | Where it comes from |
|---|---|
| Feature directory | `.scratch/<feature>/...` paths in skill arguments or written by `Write`/`Edit` |
| Local ticket or spec | A `.scratch/...md` path, or a bare number such as `/implement 2` that matches `.scratch/*/issues/02-*.md` |
| GitHub issue or PR | `#N` or a GitHub URL in skill arguments, `gh issue view/edit/comment/close N`, or the URL printed by `gh issue create` |
| Feature branch | The session's git branch, unless it is `master`, `main` or `development` |
| Commits | The `Session-Id` trailer in the commit message (full id or at least 8 characters) |

A `/implement` with free text and no ticket is still grouped by its branch and
its commits. A `/grill-with-docs` or `/wayfinder` session has nothing to
reference yet, so it is attached to the `/to-spec` or `/to-tickets` session that
follows within 24 hours, marked "(by time)".

Local files are read for their title and `Status:` line; GitHub issues through
`gh issue view` (title, state and URL), cached for 6 hours in
`.claude/usage/gh-cache.json`. If `gh` is missing, offline or unauthenticated the
report still builds and shows the reference as unresolved. Only titles and
states are read, never bodies, and free-text prompts are never parsed for
references. The grouping is a heuristic and the page says so.

## Privacy

Transcripts contain code and paths. The report holds only numbers, names of
skills and models, and session ids. Keep it local; `.claude/usage/` is ignored by
git.

## Usage tracking

Cost, context peak and duration as reported by the status line exist only while
usage tracking is on (`scripts/usage-tracking.sh on|off|status`). Sessions from
before that have tokens and skills but no cost.
