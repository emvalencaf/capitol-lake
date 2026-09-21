#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///
# ruff: noqa: E501  (embedded HTML and CSS)
"""Build a self-contained HTML usage dashboard from Claude Code transcripts."""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import views
import work_links
from common import esc, fmt_int, fmt_tok, parse_ts
from tools_subagents import ToolTracker, parse_subagents

PROJECTS = Path.home() / ".claude" / "projects"
COMMAND_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
INTENT_KEYWORDS = [
    ("fix", r"\b(fix|bug|error|broken|fail\w*|crash\w*|corrig\w*|erro)\b"),
    ("test", r"\b(test\w*|tdd|teste\w*)\b"),
    ("docs", r"\b(docs?|readme|documenta\w*|changelog)\b"),
    ("refactor", r"\b(refactor\w*|rename|renome\w*|cleanup|simplif\w*)\b"),
    ("review", r"\b(review|revis\w*)\b"),
    ("research", r"\b(research|investig\w*|pesquis\w*|explain|explique)\b"),
    ("feature", r"\b(add|create|implement\w*|build|adicion\w*|cri[ae]\w*|implement\w*)\b"),
]


def git_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
        ).stdout.strip()
        return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def encode_project(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path.resolve()))


def classify(text: str) -> str:
    low = text.lower()
    for name, pattern in INTENT_KEYWORDS:
        if re.search(pattern, low):
            return name
    return "conversation"


def parse_session(path: Path, root: Path) -> dict | None:
    """Return per-session numbers. Prompt text is inspected but never stored."""
    usage_by_msg: dict[str, dict] = {}
    msg_order: list[str] = []
    msg_skill: dict[str, str] = {}
    models: Counter = Counter()
    efforts: Counter = Counter()
    first_ts = last_ts = None
    current_skill = "(no skill)"
    session_skills: list[str] = []
    first_prompt_intent = None
    refs: list[dict] = []
    bare_numbers: list[int] = []
    features: set[str] = set()
    branches: Counter = Counter()
    stages: list[str] = []
    gh_create_ids: set[str] = set()
    tools = ToolTracker()

    def note_skill(name: str, args: str) -> None:
        stage = work_links.stage_of(name)
        if stage and stage not in stages:
            stages.append(stage)
        if args:
            refs.extend(work_links.extract_refs(args, root))
            bare_numbers.extend(work_links.extract_bare_numbers(args))

    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        ts = parse_ts(rec.get("timestamp", ""))
        if ts:
            first_ts = min(first_ts, ts) if first_ts else ts
            last_ts = max(last_ts, ts) if last_ts else ts
        kind = rec.get("type")
        if rec.get("gitBranch"):
            branches[rec["gitBranch"]] += 1
        msg = rec.get("message") or {}
        content = msg.get("content")

        if kind == "user":
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        tools.result(block, ts)
                    if (
                        block.get("type") == "tool_result"
                        and block.get("tool_use_id") in gh_create_ids
                    ):
                        body = block.get("content")
                        text = (
                            " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                            if isinstance(body, list)
                            else str(body or "")
                        )
                        refs.extend(r for r in work_links.extract_refs(text) if r["kind"] == "gh")
            if isinstance(content, str):
                cmd = COMMAND_RE.search(content)
                if cmd:
                    current_skill = "/" + cmd.group(1)
                    session_skills.append(current_skill)
                    args_match = COMMAND_ARGS_RE.search(content)
                    note_skill(cmd.group(1), args_match.group(1).strip() if args_match else "")
                    if first_prompt_intent is None:
                        first_prompt_intent = current_skill
                elif content.strip() and "<local-command" not in content:
                    current_skill = "(no skill)"
                    if first_prompt_intent is None:
                        first_prompt_intent = classify(content)
            continue

        if kind != "assistant":
            continue
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    tools.use(block, ts)
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    name = (block.get("input") or {}).get("skill")
                    if name:
                        current_skill = "/" + str(name).lstrip("/")
                        session_skills.append(current_skill)
                        note_skill(str(name), str((block.get("input") or {}).get("args") or ""))
                elif block.get("type") == "tool_use":
                    tool_input = block.get("input") or {}
                    if block.get("name") in ("Write", "Edit", "MultiEdit"):
                        fpath = str(tool_input.get("file_path", ""))
                        if ".scratch/" in fpath:
                            rel = fpath[fpath.index(".scratch/") :]
                            refs.append({"kind": "file", "path": rel})
                            slug = work_links.feature_of(rel)
                            if slug:
                                features.add(slug)
                    elif block.get("name") == "Bash":
                        command = str(tool_input.get("command", ""))
                        refs.extend(work_links.extract_command_refs(command))
                        if "gh issue create" in command:
                            gh_create_ids.add(block.get("id"))
        mid = msg.get("id")
        usage = msg.get("usage")
        if not mid or not usage:
            continue
        if mid not in usage_by_msg:
            msg_order.append(mid)
        usage_by_msg[mid] = usage  # streamed duplicates repeat usage; keep the last
        msg_skill[mid] = current_skill
        if msg.get("model"):
            models[msg["model"]] += 1
        if rec.get("effort"):
            efforts[rec["effort"]] += 1

    if not usage_by_msg:
        return None

    tokens_in = tokens_out = cache_read = peak_ctx = 0
    per_skill: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for mid in msg_order:
        u = usage_by_msg[mid]
        fresh = u.get("input_tokens", 0)
        created = u.get("cache_creation_input_tokens", 0)
        read = u.get("cache_read_input_tokens", 0)
        out = u.get("output_tokens", 0)
        total_in = fresh + created + read
        tokens_in += total_in
        tokens_out += out
        cache_read += read
        peak_ctx = max(peak_ctx, total_in)
        per_skill[msg_skill[mid]][0] += total_in
        per_skill[msg_skill[mid]][1] += out

    intent = first_prompt_intent or "conversation"
    return {
        "id": path.stem,
        "start": first_ts,
        "end": last_ts,
        "wall_s": int((last_ts - first_ts).total_seconds()) if first_ts and last_ts else 0,
        "model": models.most_common(1)[0][0] if models else "?",
        "effort": efforts.most_common(1)[0][0] if efforts else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_read": cache_read,
        "peak_ctx_tokens": peak_ctx,
        "skills": Counter(session_skills),
        "per_skill": dict(per_skill),
        "intent": intent,
        "refs": [dict(t) for t in {tuple(sorted(r.items())) for r in refs}],
        "bare_numbers": sorted(set(bare_numbers)),
        "features": sorted(features),
        "branch": branches.most_common(1)[0][0] if branches else None,
        "stages": sorted(stages, key=lambda x: work_links.STAGE_ORDER.index(x)),
        "stages_seen": stages,
        "tools": tools.as_dict(),
        "subagents": parse_subagents(path),
    }


def load_usage_log(root: Path) -> dict[str, dict]:
    logs = {}
    for f in (root / ".claude" / "usage").glob("*.json"):
        try:
            logs[f.stem] = json.loads(f.read_text())
        except ValueError:
            continue
    return logs


def day_chart(days: list[tuple[str, int, int]]) -> str:
    """Grouped bars per day: input (series 1) and output (series 2), one axis."""
    if not days:
        return '<p class="muted">No data.</p>'
    w, h, pad_l, pad_b, pad_t = 760, 220, 46, 34, 10
    top = max(max(i, o) for _, i, o in days) or 1
    step = (w - pad_l) / len(days)
    bw = min(18, step / 2 - 3)
    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Tokens per day, input and output">'
    ]
    for frac in (0, 0.5, 1):
        y = h - pad_b - (h - pad_b - pad_t) * frac
        parts.append(f'<line class="grid" x1="{pad_l}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="axis" x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end">{fmt_tok(top * frac)}</text>'
        )
    for idx, (day, tin, tout) in enumerate(days):
        cx = pad_l + step * idx + step / 2
        for off, val, cls, name in (
            (-bw / 2 - 1, tin, "s1", "input"),
            (bw / 2 + 1, tout, "s2", "output"),
        ):
            bh = (h - pad_b - pad_t) * val / top
            parts.append(
                f'<rect class="{cls}" x="{cx + off - bw / 2:.1f}" y="{h - pad_b - bh:.1f}" '
                f'width="{bw:.1f}" height="{max(bh, 0.5):.1f}" rx="3"><title>{esc(day)} {name}: {fmt_int(val)} tokens</title></rect>'
            )
        if len(days) <= 14 or idx % max(1, len(days) // 10) == 0:
            parts.append(
                f'<text class="axis" x="{cx:.1f}" y="{h - 14}" text-anchor="middle">{esc(day[5:])}</text>'
            )
    parts.append("</svg>")
    legend = (
        '<p class="legend"><span class="sw s1"></span> Input (fresh + cache) '
        '<span class="sw s2"></span> Output</p>'
    )
    return legend + "".join(parts)


def render(
    sessions: list[dict], logs: dict, args, scope: str, groups: list[dict], tracker: str
) -> str:
    total_in = sum(s["tokens_in"] for s in sessions)
    total_out = sum(s["tokens_out"] for s in sessions)
    total_cache = sum(s["cache_read"] for s in sessions)
    with_cost = [logs[s["id"]] for s in sessions if s["id"] in logs]
    est_cost = sum(r.get("cost_usd_estimated", 0) for r in with_cost)
    subs = [a for s in sessions for a in s.get("subagents") or []]
    sub_in = sum(a["tokens_in"] for a in subs)
    sub_out = sum(a["tokens_out"] for a in subs)

    per_day: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in sessions:
        if s["start"]:
            d = s["start"].astimezone().strftime("%Y-%m-%d")
            per_day[d][0] += s["tokens_in"]
            per_day[d][1] += s["tokens_out"]
    days = [(d, v[0], v[1]) for d, v in sorted(per_day.items())]

    skill_count: Counter = Counter()
    skill_sessions: Counter = Counter()
    skill_tok: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    intents: Counter = Counter()
    for s in sessions:
        intents[s["intent"]] += 1
        for name, n in s["skills"].items():
            skill_count[name] += n
            skill_sessions[name] += 1
        for name, (i, o) in s["per_skill"].items():
            skill_tok[name][0] += i
            skill_tok[name][1] += o

    top_skills = skill_count.most_common(args.top)
    skill_rows = [
        (
            n,
            c,
            f"{n}: {c} calls in {skill_sessions[n]} sessions, ~{fmt_int(skill_tok[n][0])} in / ~{fmt_int(skill_tok[n][1])} out (approximate)",
        )
        for n, c in top_skills
    ]
    skill_table = (
        "".join(
            f"<tr><td>{esc(n)}</td><td class='num'>{c}</td><td class='num'>{skill_sessions[n]}</td>"
            f"<td class='num'>~{fmt_tok(skill_tok[n][0])}</td><td class='num'>~{fmt_tok(skill_tok[n][1])}</td></tr>"
            for n, c in top_skills
        )
        or "<tr><td colspan='5' class='muted'>No skill calls recorded.</td></tr>"
    )
    unattributed = skill_tok.get("(no skill)", [0, 0])
    intent_rows = [
        (n, c, f"{n}: {c} sessions (heuristic)") for n, c in intents.most_common(args.top)
    ]

    cost_note = (
        f"{len(with_cost)} of {len(sessions)} sessions have a logged estimate"
        if sessions
        else "no sessions"
    )
    kpis = (
        '<section class="kpis">'
        f'<div class="kpi"><b>{len(sessions)}</b><span>sessions</span></div>'
        f'<div class="kpi"><b>{fmt_tok(total_in)}</b><span>input tokens, main sessions (cache read '
        f"{f'{total_cache / total_in * 100:.0f}%' if total_in else '--'})</span></div>"
        f'<div class="kpi"><b>{fmt_tok(total_out)}</b><span>output tokens, main sessions</span></div>'
        f'<div class="kpi"><b>{len(subs)}</b><span>subagents &middot; {fmt_tok(sub_in)} in / {fmt_tok(sub_out)} out, '
        "not included in the tokens above</span></div>"
        f'<div class="kpi"><b>{f"~$ {est_cost:.2f}" if with_cost else "n/a"}</b><span>estimated cost &middot; {esc(cost_note)}</span></div>'
        "</section>"
    )
    overview = (
        kpis
        + f'<section class="card"><h2>Tokens per day (main sessions)</h2>{day_chart(days)}</section>'
        + f'<section class="card"><h2>Most used skills</h2>{views.bar_rows(skill_rows)}'
        "<details><summary>Table view: calls, sessions and approximate tokens</summary>"
        "<table><thead><tr><th>Skill</th><th class='num'>Calls</th><th class='num'>Sessions</th>"
        "<th class='num'>~In</th><th class='num'>~Out</th></tr></thead>"
        f"<tbody>{skill_table}</tbody></table>"
        f"<p class='muted'>Tokens outside any skill: {fmt_tok(unattributed[0])} in / {fmt_tok(unattributed[1])} out. "
        "Per-skill tokens run from the skill call until your next prompt.</p></details></section>"
        + f'<section class="card"><h2>Intents (heuristic)</h2>{views.bar_rows(intent_rows)}</section>'
        + views.tools_card(sessions, args.top)
    )
    panels = [
        ("overview", "Overview", overview),
        ("work", "Work", views.work_section(groups, logs, tracker)),
        ("types", "By type", views.types_tab(groups, sessions)),
        ("sessions", "Sessions", views.sessions_table(sessions, logs, args.limit)),
    ]
    return TEMPLATE.format(
        scope=esc(scope),
        generated=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        tabs=views.tabs(panels),
    )


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Usage report</title>
<style>
:root {{ color-scheme: light; --surface:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink2:#52514e; --grid:#e3e2de; --s1:#2a78d6; --s2:#eb6834; --warn-bg:#fff4d6; --warn-ink:#5c4300; }}
@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) {{ color-scheme: dark; --surface:#1a1a19; --card:#232322; --ink:#ffffff; --ink2:#c3c2b7; --grid:#3a3a38; --s1:#3987e5; --s2:#d95926; --warn-bg:#3a2f0f; --warn-ink:#f3d98b; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --card:#232322; --ink:#ffffff; --ink2:#c3c2b7; --grid:#3a3a38; --s1:#3987e5; --s2:#d95926; --warn-bg:#3a2f0f; --warn-ink:#f3d98b; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--surface); color:var(--ink); font:15px/1.5 system-ui,sans-serif; }}
main {{ max-width:1000px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:0 0 12px; }}
.muted {{ color:var(--ink2); }} .mono {{ font-family:ui-monospace,monospace; }}
.notice {{ background:var(--warn-bg); color:var(--warn-ink); border-radius:8px; padding:10px 14px; margin:16px 0; font-size:14px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:16px 0; }}
.kpi, .card {{ background:var(--card); border:1px solid var(--grid); border-radius:10px; padding:14px 16px; }}
.kpi b {{ display:block; font-size:24px; }} .kpi span {{ color:var(--ink2); font-size:13px; }}
.card {{ margin:16px 0; overflow-x:auto; }}
.bar-row {{ display:grid; grid-template-columns:150px 1fr 64px; gap:10px; align-items:center; padding:3px 0; }}
.bar-label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.bar-track {{ display:block; }} .bar-fill {{ display:block; height:12px; background:var(--s1); border-radius:0 4px 4px 0; }}
.bar-value {{ text-align:right; color:var(--ink2); font-variant-numeric:tabular-nums; }}
svg {{ width:100%; height:auto; }} .grid {{ stroke:var(--grid); stroke-width:1; }} .axis {{ fill:var(--ink2); font-size:11px; }}
rect.s1 {{ fill:var(--s1); }} rect.s2 {{ fill:var(--s2); }}
.sw {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin:0 4px 0 12px; }} .sw.s1 {{ background:var(--s1); }} .sw.s2 {{ background:var(--s2); }}
.legend {{ margin:0 0 6px; font-size:13px; color:var(--ink2); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }} th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--grid); white-space:nowrap; }}
th {{ color:var(--ink2); font-weight:600; }} .num {{ text-align:right; font-variant-numeric:tabular-nums; }} .est {{ font-style:italic; }}
.work {{ border-top:1px solid var(--grid); padding-top:12px; margin-top:12px; }} .work h3 {{ font-size:15px; margin:0 0 4px; }} .refs {{ margin:6px 0; padding-left:18px; font-size:13px; }} code {{ font-family:ui-monospace,monospace; font-size:12px; }}
details summary {{ cursor:pointer; color:var(--ink2); font-size:13px; margin-top:8px; }}
.tabs {{ margin-top:16px; }} .tab-input {{ position:absolute; opacity:0; pointer-events:none; }}
.tab-nav {{ display:flex; gap:4px; border-bottom:1px solid var(--grid); flex-wrap:wrap; }}
.tab-nav label {{ padding:8px 14px; cursor:pointer; color:var(--ink2); border-bottom:2px solid transparent; font-weight:600; }}
.panel {{ display:none; }}
#t-overview:checked ~ .tab-nav label[for=t-overview] {{ color:var(--ink); border-bottom-color:var(--s1); }} #t-overview:checked ~ #p-overview {{ display:block; }} #t-overview:focus-visible ~ .tab-nav label[for=t-overview] {{ outline:2px solid var(--s1); }}
#t-work:checked ~ .tab-nav label[for=t-work] {{ color:var(--ink); border-bottom-color:var(--s1); }} #t-work:checked ~ #p-work {{ display:block; }} #t-work:focus-visible ~ .tab-nav label[for=t-work] {{ outline:2px solid var(--s1); }}
#t-types:checked ~ .tab-nav label[for=t-types] {{ color:var(--ink); border-bottom-color:var(--s1); }} #t-types:checked ~ #p-types {{ display:block; }} #t-types:focus-visible ~ .tab-nav label[for=t-types] {{ outline:2px solid var(--s1); }}
#t-sessions:checked ~ .tab-nav label[for=t-sessions] {{ color:var(--ink); border-bottom-color:var(--s1); }} #t-sessions:checked ~ #p-sessions {{ display:block; }} #t-sessions:focus-visible ~ .tab-nav label[for=t-sessions] {{ outline:2px solid var(--s1); }}
.small {{ font-size:11px; font-family:system-ui,sans-serif; }} .badge {{ display:inline-block; font-size:11px; padding:1px 7px; border-radius:999px; border:1px solid var(--ink2); color:var(--ink2); }} .badge.type {{ border-color:var(--s1); color:var(--ink); }}
tr.sub td {{ background:color-mix(in srgb, var(--grid) 35%, transparent); color:var(--ink2); }} tr.sub td:first-child {{ padding-left:22px; }}
</style>
</head>
<body>
<main>
<h1>Usage report</h1>
<p class="muted">{scope} &middot; generated {generated}</p>
<div class="notice"><b>Estimated values.</b> Cost (marked <i>~$</i> and in italics) is the estimate Claude Code computed on your machine and the status line logged. It is not your invoice, and sessions from before usage tracking was enabled have none. Tokens per skill are approximate, and intents and work groupings are heuristics, not what you really meant. Subagents are reported separately and never added to the session that spawned them.</div>
{tabs}
</main>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="every project under ~/.claude/projects")
    ap.add_argument("--since", help="ignore sessions that started before YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=10, help="rows in rankings (default 10, max 50)")
    ap.add_argument(
        "--limit", type=int, default=25, help="rows in sessions table (default 25, max 200)"
    )
    ap.add_argument(
        "--tracker",
        choices=["auto", "local", "github"],
        default="auto",
        help="how to read bare ticket numbers (default: from docs/agents/issue-tracker.md)",
    )
    ap.add_argument(
        "--offline", action="store_true", help="never call gh; GitHub refs stay unresolved"
    )
    ap.add_argument("--transcripts", help="read transcripts from this directory instead (testing)")
    ap.add_argument("-o", "--output", help="output HTML path")
    args = ap.parse_args()
    args.top = min(max(args.top, 1), 50)
    args.limit = min(max(args.limit, 1), 200)

    root = git_root()
    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since).astimezone()
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got: {args.since}", file=sys.stderr)
            return 1

    if args.transcripts:
        dirs = [Path(args.transcripts)]
        scope = root.name
    elif args.all:
        dirs = [d for d in PROJECTS.iterdir() if d.is_dir()] if PROJECTS.exists() else []
        scope = f"all projects ({len(dirs)})"
    else:
        dirs = [PROJECTS / encode_project(root)]
        scope = root.name
    files = [f for d in dirs if d.exists() for f in d.glob("*.jsonl")]
    if not files:
        print(f"no transcripts found for {scope} under {PROJECTS}", file=sys.stderr)
        return 1

    sessions = [s for f in files if (s := parse_session(f, root))]
    if since:
        sessions = [s for s in sessions if s["start"] and s["start"] >= since]
    logs = load_usage_log(root)

    tracker = args.tracker if args.tracker != "auto" else work_links.detect_tracker(root)
    groups = work_links.build_groups(
        sessions, root, tracker, args.offline, root / ".claude" / "usage" / "gh-cache.json"
    )

    out = Path(args.output) if args.output else root / ".claude" / "usage" / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(sessions, logs, args, scope, groups, tracker), encoding="utf-8")
    print(
        f"{out}  ({len(sessions)} sessions, {sum(1 for s in sessions if s['id'] in logs)} with logged cost estimate)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
