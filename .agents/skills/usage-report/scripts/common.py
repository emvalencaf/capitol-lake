"""Small helpers shared by the usage report modules."""

import html
from datetime import datetime


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def fmt_int(n: float) -> str:
    return f"{int(n):,}"


def fmt_tok(n: float) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def fmt_dur(seconds: float) -> str:
    s = int(seconds)
    if s <= 0:
        return "--"
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def esc(v) -> str:
    return html.escape(str(v))
