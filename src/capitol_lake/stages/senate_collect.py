"""Senate collector: pure decision logic for `/ptr/` eFD filings.

The Senate eFD search UI is Akamai bot/fingerprint-protected (#17, #23): a
scripted request to its search endpoint 403s even from a plain sandboxed
environment, and headless-browser bypass from a cloud egress IP is unverified
(#28, #29). Per #18's resolution, the Senate collector therefore stays out of
the automated cloud pipeline and is run locally by a human who has already
completed the site's access/agreement flow; `rows` here is that human's
already-exported search-result set (one dict per row), not bytes this module
fetches itself.

Given `rows`, `parse_senate_index` routes and filters to `/ptr/` filings only
(`/paper/` scanned-GIF rows are skipped, never fetched), and `collect_senate`
rate-limits the individual filing fetches (~1 request/second) and drives the
chamber-agnostic `bronze_write` contract, exactly as `house_collect` does.
Network and S3 access are injected as callables, so this is testable with no
live network call; only `capitol_lake.handlers.senate_collect_handler` wires
it to a real HTTP client.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from capitol_lake.keys import bronze_key, bronze_meta_key
from capitol_lake.stages.bronze_write import bronze_write

# Confirm against a recorded filing page before a first production run.
SENATE_FILING_URL_TEMPLATE = "https://efdsearch.senate.gov/search/view/ptr/{filing_id}/"

PTR_FILING_KIND = "ptr"
PAPER_FILING_KIND = "paper"


class UnknownFilingKindError(ValueError):
    """A row's filing type doesn't match any known Senate filing kind."""


def route_filing_kind(raw_kind: str) -> str:
    """Classify a raw Senate filing-type string as `"ptr"` or `"paper"`.

    `/ptr/` filings are electronic, clean HTML and in scope. `/paper/`
    filings are pre-electronic-mandate scanned GIFs, out of scope (#30).
    Anything else is a filing type this collector doesn't recognize.
    """
    normalized = raw_kind.strip().lower()
    if normalized == PTR_FILING_KIND:
        return PTR_FILING_KIND
    if normalized == PAPER_FILING_KIND:
        return PAPER_FILING_KIND
    raise UnknownFilingKindError(f"unrecognized Senate filing kind: {raw_kind!r}")


def senate_filing_url(filing_id: str) -> str:
    """Source URL for a `/ptr/` filing's HTML page."""
    return SENATE_FILING_URL_TEMPLATE.format(filing_id=filing_id)


@dataclass(frozen=True)
class SenateIndexEntry:
    """One routed row from a Senate eFD search-result export."""

    filing_id: str
    year: int
    kind: str  # "ptr" (only kind this collector fetches)
    index_row: int


def parse_senate_index(rows: list[dict], year: int) -> list[SenateIndexEntry]:
    """Route and filter search-result rows to `/ptr/` filing entries.

    Rows without a `filing_id`, rows whose `filing_type` isn't recognized,
    and `/paper/` rows are all skipped rather than raised, since the
    exported result set also lists filing types this collector doesn't
    handle. Amendments carry their own separate `filing_id` (a Senate eFD
    UUID, per #17) and so appear as their own independent entry here.
    """
    entries = []
    for row, raw in enumerate(rows):
        filing_id = (raw.get("filing_id") or "").strip()
        if not filing_id:
            continue
        try:
            kind = route_filing_kind(raw.get("filing_type", ""))
        except UnknownFilingKindError:
            continue
        if kind != PTR_FILING_KIND:
            continue
        entries.append(SenateIndexEntry(filing_id=filing_id, year=year, kind=kind, index_row=row))
    return entries


@dataclass
class RateLimiter:
    """Sleeps as needed to keep calls to `wait()` at least `min_interval` apart."""

    min_interval: float = 1.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_call: float | None = field(default=None, init=False, repr=False)

    def wait(self) -> None:
        now = self.clock()
        if self._last_call is not None:
            remaining = self.min_interval - (now - self._last_call)
            if remaining > 0:
                self.sleep(remaining)
                now = self.clock()
        self._last_call = now


def collect_senate(
    year: int,
    rows: list[dict],
    *,
    fetch_filing: Callable[[str], bytes],
    read_existing_sha256: Callable[[str], str | None],
    write_bytes: Callable[[str, bytes], None],
    now: Callable[[], str],
    rate_limiter: RateLimiter | None = None,
) -> dict:
    """Collect one year of Senate `/ptr/` filings into bronze.

    Routes and filters `rows` to `/ptr/` entries via `parse_senate_index`,
    then downloads each filing's HTML via `fetch_filing(url)` (rate-limited
    by `rate_limiter`, ~1 request/second by default) and writes it through
    the hash-gated `bronze_write` contract: `read_existing_sha256(meta_key)`
    supplies the prior hash and `write_bytes(key, bytes)` performs the
    actual write, both skipped entirely when `bronze_write` decides the
    candidate is a no-op. A filing's UUID (and an amendment's own, separate
    UUID) is used as `doc_id` unchanged, so the existing idempotency
    contract applies without modification. Network and storage access are
    fully injected so this function runs against fakes in tests, with no
    live network call and no real S3.
    """
    rate_limiter = rate_limiter or RateLimiter()
    entries = parse_senate_index(rows, year)

    written: list[str] = []
    noop: list[str] = []
    for entry in entries:
        rate_limiter.wait()

        url = senate_filing_url(entry.filing_id)
        candidate_bytes = fetch_filing(url)
        meta_key = bronze_meta_key(bronze_key("senate", entry.year, entry.filing_id, "html"))
        existing_sha256 = read_existing_sha256(meta_key)

        plan = bronze_write(
            chamber="senate",
            year=entry.year,
            doc_id=entry.filing_id,
            ext="html",
            candidate_bytes=candidate_bytes,
            existing_sha256=existing_sha256,
            source_url=url,
            fetched_at=now(),
            index_row=entry.index_row,
        )

        if plan["action"] == "noop":
            noop.append(plan["key"])
            continue

        meta = {**plan["meta"], "kind": entry.kind}
        write_bytes(plan["key"], candidate_bytes)
        write_bytes(plan["meta_key"], json.dumps(meta).encode("utf-8"))
        written.append(plan["key"])

    return {"year": year, "written": written, "noop": noop}
