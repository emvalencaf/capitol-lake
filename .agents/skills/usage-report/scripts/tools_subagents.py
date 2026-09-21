"""Tool usage and subagent transcripts.

Tools are tracked by name only: calls, errors and elapsed time between a call and
its result. Subagents are read from `<session>/subagents/agent-*.jsonl` and kept
as separate entries linked to the session that spawned them. Their numbers are
never added to the parent session's totals.
"""

import json
from collections import Counter
from pathlib import Path

from common import parse_ts


class ToolTracker:
    """Counts tool calls, errors and call-to-result time, per tool name."""

    def __init__(self) -> None:
        self.calls: Counter = Counter()
        self.errors: Counter = Counter()
        self.seconds: Counter = Counter()
        self._pending: dict[str, tuple[str, object]] = {}
        self._seen: set[str] = set()

    def use(self, block: dict, ts) -> None:
        tid, name = block.get("id"), block.get("name")
        if not tid or not name or tid in self._seen:
            return
        self._seen.add(tid)
        self.calls[name] += 1
        self._pending[tid] = (name, ts)

    def result(self, block: dict, ts) -> None:
        entry = self._pending.pop(block.get("tool_use_id"), None)
        if not entry:
            return
        name, started = entry
        if ts and started:
            self.seconds[name] += max(0.0, (ts - started).total_seconds())
        if block.get("is_error"):
            self.errors[name] += 1

    def as_dict(self) -> dict:
        return {
            "calls": dict(self.calls),
            "errors": dict(self.errors),
            "seconds": {k: round(v, 1) for k, v in self.seconds.items()},
        }


def _read_meta(path: Path) -> dict:
    try:
        return json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def parse_subagent(path: Path) -> dict | None:
    """One subagent transcript. The prompt sent to it is never read into the result."""
    meta = _read_meta(path)
    usage_by_msg: dict[str, dict] = {}
    models: Counter = Counter()
    tools = ToolTracker()
    first_ts = last_ts = None

    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        ts = parse_ts(rec.get("timestamp", ""))
        if ts:
            first_ts = min(first_ts, ts) if first_ts else ts
            last_ts = max(last_ts, ts) if last_ts else ts
        msg = rec.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    tools.use(block, ts)
                elif block.get("type") == "tool_result":
                    tools.result(block, ts)
        if rec.get("type") == "assistant" and msg.get("usage") and msg.get("id"):
            usage_by_msg[msg["id"]] = msg["usage"]  # streamed duplicates: keep the last
            if msg.get("model"):
                models[msg["model"]] += 1

    if not usage_by_msg:
        return None
    tokens_in = tokens_out = cache_read = peak = 0
    for u in usage_by_msg.values():
        total_in = (
            u.get("input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
        )
        tokens_in += total_in
        tokens_out += u.get("output_tokens", 0)
        cache_read += u.get("cache_read_input_tokens", 0)
        peak = max(peak, total_in)
    return {
        "agent_id": path.stem.removeprefix("agent-"),
        "type": meta.get("agentType") or "unknown",
        "spawn_depth": meta.get("spawnDepth"),
        "model": models.most_common(1)[0][0] if models else "?",
        "start": first_ts,
        "end": last_ts,
        "wall_s": int((last_ts - first_ts).total_seconds()) if first_ts and last_ts else 0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cache_read": cache_read,
        "peak_ctx_tokens": peak,
        "tools": tools.as_dict(),
    }


def parse_subagents(session_file: Path) -> list[dict]:
    """Subagents spawned by a session, oldest first."""
    folder = session_file.with_suffix("") / "subagents"
    found = [a for f in sorted(folder.glob("agent-*.jsonl")) if (a := parse_subagent(f))]
    return sorted(found, key=lambda a: a["start"].timestamp() if a["start"] else 0)
