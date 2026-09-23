"""Senate collector: pure decision logic for `/ptr/` eFD filings.

The Senate eFD search UI is Akamai bot/fingerprint-protected (#17, #23): a
plain scripted request (no JS engine, no browser TLS/header fingerprint) 403s
even against the individual `/ptr/` filing pages, confirmed live — only a
real browser engine (headless Chromium via Selenium, reusing session cookies
does *not* help a plain HTTP client) gets through. Per #18, the Senate
collector therefore stays out of the automated cloud pipeline and is run
locally by a human (or a local headless-browser step) that completes the
site's agreement flow and captures results; `response` here is that
already-captured JSON body from the eFD search UI's own DataTables endpoint
(`POST /search/report/data/`) — this module never scripts the search itself.

`response["data"]` is a list of 5-element rows,
`[first_name, last_name, office, html_link, filed_date]`, where `html_link`
is an anchor like `<a href="/search/view/ptr/{uuid}/">...</a>` (confirmed
against a real, recorded response — see `tests/fixtures/senate_search_sample.json`).
`parse_senate_index` extracts each row's filing kind and UUID from that
anchor and its year from `filed_date`, keeping `/ptr/` entries only —
`/paper/` (scanned-GIF) and every other report kind (`annual`,
`extension-notice/regular`, ...) are skipped, never fetched. `collect_senate`
then rate-limits the individual filing fetches (~1 request/second) and
drives the chamber-agnostic `bronze_write` contract, exactly as
`house_collect` does. Network and S3 access are injected as callables, so
this is testable with no live network call; only
`capitol_lake.handlers.senate_collect_handler` wires it to a real HTTP
client.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from capitol_lake.keys import bronze_key, bronze_meta_key
from capitol_lake.stages.bronze_write import bronze_write

# Confirmed live: GET on this exact path (no session/agreement cookie
# required) returns the filing's HTML when the request clears Akamai.
SENATE_FILING_URL_TEMPLATE = "https://efdsearch.senate.gov/search/view/ptr/{filing_id}/"

PTR_FILING_KIND = "ptr"
PAPER_FILING_KIND = "paper"

# Matches an eFD search-result row's link, e.g.
# `<a href="/search/view/ptr/b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f/" ...>`.
# `kind` can be a single segment (`ptr`, `paper`, `annual`, ...) or two
# (`extension-notice/regular`); only a single-segment `ptr` kind survives
# `route_filing_kind` below.
_FILING_LINK_RE = re.compile(
    r'href="/search/view/(?P<kind>[a-z0-9_-]+(?:/[a-z0-9_-]+)?)/'
    r"(?P<filing_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/"'
)


class UnknownFilingKindError(ValueError):
    """A row's filing kind doesn't match any kind this collector handles."""


def route_filing_kind(raw_kind: str) -> str:
    """Classify a raw Senate filing-kind path segment as `"ptr"` or `"paper"`.

    `/ptr/` filings are electronic, clean HTML and in scope. `/paper/`
    filings are pre-electronic-mandate scanned GIFs, out of scope (#30).
    Every other kind the eFD search surfaces (`annual`,
    `extension-notice/regular`, ...) isn't a PTR at all and is likewise not
    recognized here.
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
    """One routed row from a captured eFD search-result response."""

    filing_id: str
    year: int
    kind: str  # "ptr" (only kind this collector fetches)
    index_row: int


def parse_senate_index(response: dict) -> list[SenateIndexEntry]:
    """Route and filter a captured eFD search response to `/ptr/` entries.

    `response` is the JSON body the eFD search UI's own DataTables endpoint
    returns (`{"data": [[first, last, office, html_link, filed_date], ...],
    ...}`); this module never issues that search request itself (see module
    docstring). Rows whose link doesn't match a known filing path, and rows
    whose kind isn't `/ptr/` (including `/paper/`), are skipped rather than
    raised, since a real search response also lists report kinds this
    collector doesn't handle. Amendments carry their own separate UUID (per
    #17) and so appear as their own independent entry here. A row's year
    comes from its `filed_date` column (`MM/DD/YYYY`), since the response
    isn't scoped to a single year the way the House annual index is — this is
    the date the report was *filed*, not necessarily the disclosure period it
    covers (a January filing can report prior-year transactions), so bronze's
    `year=` partition is filed-year, an approximation good enough for
    idempotent storage but worth remembering if a later stage assumes it's
    the transaction year.
    """
    entries = []
    for row, raw in enumerate(response.get("data", [])):
        if len(raw) < 5:
            continue
        match = _FILING_LINK_RE.search(raw[3] or "")
        if match is None:
            continue
        try:
            kind = route_filing_kind(match.group("kind"))
        except UnknownFilingKindError:
            continue
        if kind != PTR_FILING_KIND:
            continue
        try:
            year = int((raw[4] or "").strip().split("/")[-1])
        except (ValueError, IndexError):
            continue
        entries.append(
            SenateIndexEntry(
                filing_id=match.group("filing_id"), year=year, kind=kind, index_row=row
            )
        )
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
    response: dict,
    *,
    fetch_filing: Callable[[str], bytes],
    read_existing_sha256: Callable[[str], str | None],
    write_bytes: Callable[[str, bytes], None],
    now: Callable[[], str],
    rate_limiter: RateLimiter | None = None,
) -> dict:
    """Collect the `/ptr/` filings in a captured Senate eFD search response into bronze.

    Routes and filters `response` to `/ptr/` entries via `parse_senate_index`,
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
    entries = parse_senate_index(response)

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

    return {"years": sorted({e.year for e in entries}), "written": written, "noop": noop}
