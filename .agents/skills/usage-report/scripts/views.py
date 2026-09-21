# ruff: noqa: E501  (embedded HTML)
"""HTML fragments for the dashboard tabs.

Subagents are always shown as their own rows, marked "subagent" and nested under
the session that spawned them. Their numbers are never added to that session.
"""

from collections import Counter, defaultdict
from datetime import datetime

import work_links
from common import esc, fmt_dur, fmt_int, fmt_tok


def bar_rows(rows: list[tuple[str, float, str]], unit: str = "") -> str:
    """Horizontal bars. rows: (label, value, tooltip). One series, so one color."""
    if not rows:
        return '<p class="muted">No data.</p>'
    top = max(v for _, v, _ in rows) or 1
    out = ['<div class="bars" role="list">']
    for label, value, tip in rows:
        pct = max(value / top * 100, 0.5)
        shown = fmt_tok(value) if unit == "tok" else fmt_int(value)
        out.append(
            f'<div class="bar-row" role="listitem" title="{esc(tip)}">'
            f'<span class="bar-label">{esc(label)}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="bar-value">{esc(shown)}</span></div>'
        )
    out.append("</div>")
    return "".join(out)


def tabs(panels: list[tuple[str, str, str]]) -> str:
    """CSS-only tabs. panels: (id, label, html)."""
    inputs = "".join(
        f'<input type="radio" name="tab" id="t-{pid}" class="tab-input"{" checked" if i == 0 else ""}>'
        for i, (pid, _, _) in enumerate(panels)
    )
    nav = "".join(f'<label for="t-{pid}">{esc(label)}</label>' for pid, label, _ in panels)
    body = "".join(f'<div class="panel" id="p-{pid}">{content}</div>' for pid, _, content in panels)
    return f'<div class="tabs">{inputs}<nav class="tab-nav">{nav}</nav>{body}</div>'


def _local(dt: datetime | None, fmt: str) -> str:
    return dt.astimezone().strftime(fmt) if dt else "--"


def _top_tools(tools: dict, n: int = 3) -> str:
    calls = Counter(tools.get("calls", {}))
    return " · ".join(f"{esc(name)}x{c}" for name, c in calls.most_common(n)) or "--"


def sub_summary(session: dict) -> tuple[int, int, int]:
    subs = session.get("subagents") or []
    return len(subs), sum(a["tokens_in"] for a in subs), sum(a["tokens_out"] for a in subs)


def sub_note(session: dict) -> str:
    n, tin, tout = sub_summary(session)
    if not n:
        return ""
    return (
        f"<br><span class='muted small'>+{n} subagent{'s' if n != 1 else ''}: "
        f"{fmt_tok(tin)} in / {fmt_tok(tout)} out, separate</span>"
    )


def sub_row(a: dict, cols: int = 11) -> str:
    """A subagent row. `cols` matches the sessions table layout."""
    return (
        f"<tr class='sub'><td><span class='badge'>subagent</span> <span class='mono'>{esc(a['agent_id'][:8])}</span></td>"
        f"<td>{_local(a['start'], '%Y-%m-%d %H:%M')}</td><td class='num'>{fmt_dur(a['wall_s'])}</td>"
        f"<td>{esc(a['model'])}</td><td>--</td>"
        f"<td class='num'><span class='muted'>({fmt_tok(a['peak_ctx_tokens'])})</span></td>"
        f"<td class='num'>{fmt_tok(a['tokens_in'])}</td><td class='num'>{fmt_tok(a['tokens_out'])}</td>"
        f"<td class='num est'>n/a</td><td>{esc(a['type'])}</td><td class='muted'>{_top_tools(a['tools'])}</td></tr>"
    )


def sessions_table(sessions: list[dict], logs: dict, limit: int) -> str:
    ordered = sorted(sessions, key=lambda s: s["start"] or datetime.min.astimezone(), reverse=True)
    rows = []
    for s in ordered[:limit]:
        rec = logs.get(s["id"], {})
        cost = f"~$ {rec['cost_usd_estimated']:.2f}" if "cost_usd_estimated" in rec else "n/a"
        dur = fmt_dur(rec["duration_ms"] / 1000) if rec.get("duration_ms") else fmt_dur(s["wall_s"])
        peak = f"{rec['context_peak_pct']:.0f}%" if rec.get("context_peak_pct") else "--"
        rows.append(
            f"<tr><td class='mono'>{esc(s['id'][:8])}{sub_note(s)}</td><td>{_local(s['start'], '%Y-%m-%d %H:%M')}</td>"
            f"<td class='num'>{dur}</td><td>{esc(s['model'])}</td><td>{esc(rec.get('effort') or s['effort'] or '--')}</td>"
            f"<td class='num'>{peak} <span class='muted'>({fmt_tok(s['peak_ctx_tokens'])})</span></td>"
            f"<td class='num'>{fmt_tok(s['tokens_in'])}</td><td class='num'>{fmt_tok(s['tokens_out'])}</td>"
            f"<td class='num est'>{cost}</td><td>{esc(s['intent'])}</td><td class='muted'>{_top_tools(s['tools'])}</td></tr>"
        )
        rows.extend(sub_row(a) for a in s.get("subagents") or [])
    return (
        f'<section class="card"><h2>Sessions (latest {limit})</h2>'
        + "<table><thead><tr><th>Session</th><th>Started</th><th class='num'>Duration</th><th>Model</th><th>Effort</th>"
        "<th class='num'>Context peak</th><th class='num'>In</th><th class='num'>Out</th><th class='num'>Est. cost</th>"
        "<th>Intent / type</th><th>Top tools</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        "<p class='muted'>Session ids match the first 8 characters of the Session-Id commit trailer. Rows marked "
        "<span class='badge'>subagent</span> belong to the session above them; their tokens, duration and tools are "
        "reported on their own and are <b>not</b> included in that session's numbers. Cost is the status line's "
        "estimate for the main session only; it is not split by subagent and whether it includes them is unverified.</p></section>"
    )


def _tool_table(tools_by_session: list[dict], top: int) -> str:
    calls: Counter = Counter()
    errors: Counter = Counter()
    seconds: Counter = Counter()
    sessions_using: Counter = Counter()
    for t in tools_by_session:
        calls.update(t.get("calls", {}))
        errors.update(t.get("errors", {}))
        seconds.update(t.get("seconds", {}))
        sessions_using.update(t.get("calls", {}).keys())
    rows = "".join(
        f"<tr><td>{esc(name)}</td><td class='num'>{n}</td><td class='num'>{sessions_using[name]}</td>"
        f"<td class='num'>{errors[name]}</td><td class='num'>{fmt_dur(seconds[name])}</td></tr>"
        for name, n in calls.most_common(top)
    )
    if not rows:
        return '<p class="muted">No tool calls recorded.</p>'
    return (
        "<table><thead><tr><th>Tool</th><th class='num'>Calls</th><th class='num'>Sessions</th>"
        "<th class='num'>Errors</th><th class='num'>Time</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
    )


def tools_card(sessions: list[dict], top: int) -> str:
    main = [s["tools"] for s in sessions]
    subs = [a["tools"] for s in sessions for a in s.get("subagents") or []]
    bars = bar_rows(
        [
            (n, c, f"{n}: {c} calls")
            for n, c in Counter(
                sum((Counter(t.get("calls", {})) for t in main), Counter())
            ).most_common(top)
        ]
    )
    return (
        "<section class='card'><h2>Tools</h2>"
        + bars
        + "<details><summary>Table view: main sessions</summary>"
        + _tool_table(main, top)
        + "<p class='muted'>Time runs from the call to its result, so it includes waiting for your permission. Only tool names are tracked, never inputs or outputs.</p></details>"
        + "<details><summary>Tools used by subagents (counted separately)</summary>"
        + _tool_table(subs, top)
        + "</details></section>"
    )


def work_section(groups: list[dict], logs: dict, tracker: str) -> str:
    """One card per piece of work: refs, sessions in order, subagents nested, commits."""
    if not groups:
        return (
            '<section class="card"><h2>Work</h2><p class="muted">No sessions could be linked to a spec, '
            "ticket or feature branch. Sessions that ran <code>/implement</code> on a branch or with a "
            "ticket reference appear here.</p></section>"
        )
    cards = []
    for g in groups:
        tin = sum(m["tokens_in"] for m in g["sessions"])
        tout = sum(m["tokens_out"] for m in g["sessions"])
        subs = [a for m in g["sessions"] for a in m.get("subagents") or []]
        sub_txt = (
            f" &middot; {len(subs)} subagents: {fmt_tok(sum(a['tokens_in'] for a in subs))} in / "
            f"{fmt_tok(sum(a['tokens_out'] for a in subs))} out (separate)"
            if subs
            else ""
        )
        costs = [
            logs[m["id"]]["cost_usd_estimated"]
            for m in g["sessions"]
            if m["id"] in logs and "cost_usd_estimated" in logs[m["id"]]
        ]
        cost = (
            f"~$ {sum(costs):.2f} ({len(costs)}/{len(g['sessions'])} sessions)" if costs else "n/a"
        )
        refs = []
        for f in g["files"]:
            state = f["status"] or ("found" if f["found"] else "missing")
            refs.append(
                f"<li><code>{esc(f['path'])}</code> {esc(f['title'] or '')} <span class='muted'>[{esc(state)}]</span></li>"
            )
        for i in g["gh"]:
            label = f"#{i['number']} " + (i["title"] or "")
            refs.append(
                f"<li>GitHub {esc(i['type'])} {esc(label)} <span class='muted'>[{esc(i['state'] or 'unresolved')}]</span></li>"
            )
        for n in g["unresolved"]:
            refs.append(
                f"<li>ticket {n} <span class='muted'>[unresolved: tracker is {esc(tracker)}]</span></li>"
            )
        rows = []
        for m in g["sessions"]:
            rec = logs.get(m["id"], {})
            cst = f"~$ {rec['cost_usd_estimated']:.2f}" if "cost_usd_estimated" in rec else "n/a"
            dur = (
                fmt_dur(rec["duration_ms"] / 1000)
                if rec.get("duration_ms")
                else fmt_dur(m["wall_s"])
            )
            stage = ", ".join(m["stages_seen"]) or m["intent"]
            if m.get("attached"):
                stage += " (by time)"
            rows.append(
                f"<tr><td>{esc(stage)}</td><td class='mono'>{esc(m['id'][:8])}{sub_note(m)}</td><td>{_local(m['start'], '%m-%d %H:%M')}</td>"
                f"<td class='num'>{dur}</td><td class='num'>{fmt_tok(m['tokens_in'])}</td><td class='num'>{fmt_tok(m['tokens_out'])}</td>"
                f"<td class='num est'>{cst}</td></tr>"
            )
            for a in m.get("subagents") or []:
                rows.append(
                    f"<tr class='sub'><td><span class='badge'>subagent</span> {esc(a['type'])}</td><td class='mono'>{esc(a['agent_id'][:8])}</td>"
                    f"<td>{_local(a['start'], '%m-%d %H:%M')}</td><td class='num'>{fmt_dur(a['wall_s'])}</td>"
                    f"<td class='num'>{fmt_tok(a['tokens_in'])}</td><td class='num'>{fmt_tok(a['tokens_out'])}</td><td class='num est'>n/a</td></tr>"
                )
        commits = "".join(
            f"<li><code>{esc(c['hash'])}</code> {esc(c['subject'])}</li>" for c in g["commits"]
        )
        type_badge = f"<span class='badge type'>{esc(work_links.TYPE_LABEL[g['type']])}</span> <span class='muted'>({esc(g['type_source'])})</span>"
        cards.append(
            f"<div class='work'><h3>{esc(g['title'])} {type_badge}</h3>"
            f"<p class='muted'>{len(g['sessions'])} session{'s' if len(g['sessions']) != 1 else ''} &middot; main: {fmt_tok(tin)} in / {fmt_tok(tout)} out"
            f"{sub_txt} &middot; <span class='est'>{esc(cost)}</span> &middot; branches: {esc(', '.join(g['branches']) or '--')}</p>"
            f"{'<ul class=refs>' + ''.join(refs) + '</ul>' if refs else ''}"
            "<table><thead><tr><th>Stage</th><th>Session</th><th>Started</th><th class='num'>Duration</th>"
            "<th class='num'>In</th><th class='num'>Out</th><th class='num'>Est. cost</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
            f"{'<p class=muted>Commits linked by Session-Id:</p><ul class=refs>' + commits + '</ul>' if commits else ''}</div>"
        )
    return (
        '<section class="card"><h2>Work: specs, tickets and implementation</h2>'
        '<p class="muted">Sessions are grouped by shared spec, ticket, feature directory or branch, and linked to commits '
        "through the Session-Id trailer. <b>This grouping is a heuristic</b> over references in skill arguments and tool "
        "calls, not a record of intent. Only titles and states are read, never bodies. Subagent rows and totals are "
        "kept apart from the main sessions.</p>" + "".join(cards) + "</section>"
    )


def types_tab(groups: list[dict], sessions: list[dict]) -> str:
    """Feature, bug fix, refactor... with the effort each took."""
    per: dict[str, dict] = defaultdict(
        lambda: {
            "works": [],
            "sessions": 0,
            "commits": 0,
            "in": 0,
            "out": 0,
            "subs": 0,
            "sub_in": 0,
            "sub_out": 0,
        }
    )
    grouped_ids = set()
    for g in groups:
        p = per[g["type"]]
        p["works"].append(g)
        p["sessions"] += len(g["sessions"])
        p["commits"] += len(g["commits"])
        for m in g["sessions"]:
            grouped_ids.add(m["id"])
            p["in"] += m["tokens_in"]
            p["out"] += m["tokens_out"]
            n, sin, sout = sub_summary(m)
            p["subs"] += n
            p["sub_in"] += sin
            p["sub_out"] += sout
    loose = [s for s in sessions if s["id"] not in grouped_ids]

    order = [t for t in work_links.TYPE_ORDER if t in per]
    bars = bar_rows(
        [
            (
                work_links.TYPE_LABEL[t],
                per[t]["in"] + per[t]["out"],
                f"{work_links.TYPE_LABEL[t]}: {len(per[t]['works'])} works, {per[t]['sessions']} sessions (main tokens)",
            )
            for t in order
        ],
        unit="tok",
    )
    rows = "".join(
        f"<tr><td>{esc(work_links.TYPE_LABEL[t])}</td><td class='num'>{len(per[t]['works'])}</td><td class='num'>{per[t]['sessions']}</td>"
        f"<td class='num'>{per[t]['commits']}</td><td class='num'>{fmt_tok(per[t]['in'])}</td><td class='num'>{fmt_tok(per[t]['out'])}</td>"
        f"<td class='num'>{per[t]['subs']} ({fmt_tok(per[t]['sub_in'])} in / {fmt_tok(per[t]['sub_out'])} out)</td></tr>"
        for t in order
    )
    if loose:
        lin = sum(s["tokens_in"] for s in loose)
        lout = sum(s["tokens_out"] for s in loose)
        rows += (
            f"<tr><td>No work link</td><td class='num'>0</td><td class='num'>{len(loose)}</td><td class='num'>0</td>"
            f"<td class='num'>{fmt_tok(lin)}</td><td class='num'>{fmt_tok(lout)}</td>"
            f"<td class='num'>{sum(sub_summary(s)[0] for s in loose)}</td></tr>"
        )
    lists = []
    for t in order:
        items = "".join(
            f"<li>{esc(g['title'])} <span class='muted'>({len(g['sessions'])} session{'s' if len(g['sessions']) != 1 else ''}, "
            f"{fmt_tok(sum(m['tokens_in'] for m in g['sessions']))} in / {fmt_tok(sum(m['tokens_out'] for m in g['sessions']))} out; type from {esc(g['type_source'])})</span></li>"
            for g in per[t]["works"]
        )
        lists.append(
            f"<details><summary>{esc(work_links.TYPE_LABEL[t])}: {len(per[t]['works'])} work(s)</summary><ul class='refs'>{items}</ul></details>"
        )
    body = (
        "<section class='card'><h2>Effort by type of work</h2>"
        + bars
        + "<table><thead><tr><th>Type</th><th class='num'>Works</th><th class='num'>Sessions</th><th class='num'>Commits</th>"
        "<th class='num'>In (main)</th><th class='num'>Out (main)</th><th class='num'>Subagents (separate)</th></tr></thead><tbody>"
        + rows
        + "</tbody></table>"
        "<p class='muted'>The type of each piece of work comes from, in order: the tags of its commits (the commit convention), "
        "its branch prefix, GitHub labels, then the skill that opened it. Work with none of these is shown as "
        "<b>No type signal</b>; sessions that could not be linked to any work appear as <b>No work link</b>. A work has one "
        "type, so a feature with a fix in the middle counts as a feature. Subagent tokens are not added to the main columns.</p>"
        + "".join(lists)
        + "</section>"
    )
    return body
