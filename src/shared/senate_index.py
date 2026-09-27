"""Senate eFD index parsing and rate limiting: shared across three Lambdas.

`parse_senate_index`/`SenateIndexEntry`/`senate_filing_url` route a captured
eFD search response to its `/ptr/` entries. Used by `senate_collect` (the
manual/local collection path), `senate_collect_automated` (the Playwright
session, via its own captured DataTables response), and
`senate_akamai_probe` (which only needs `SENATE_FILING_URL_TEMPLATE` to
target a filing URL directly) — three separate Lambda images, none of which
own this logic outright.

`response["data"]` is a list of 5-element rows,
`[first_name, last_name, office, html_link, filed_date]`, where `html_link`
is an anchor like `<a href="/search/view/ptr/{uuid}/">...</a>` (confirmed
against a real, recorded response — see
`tests/fixtures/senate_search_sample.json`). `parse_senate_index` extracts
each row's filing kind and UUID from that anchor and its year from
`filed_date`, keeping `/ptr/` entries only — `/paper/` (scanned-GIF) and
every other report kind (`annual`, `extension-notice/regular`, ...) are
skipped, never fetched.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

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
    ...}`); this module never issues that search request itself. Rows whose
    link doesn't match a known filing path, and rows whose kind isn't
    `/ptr/` (including `/paper/`), are skipped rather than raised, since a
    real search response also lists report kinds this collector doesn't
    handle. Amendments carry their own separate UUID (per #17) and so appear
    as their own independent entry here. A row's year comes from its
    `filed_date` column (`MM/DD/YYYY`), since the response isn't scoped to a
    single year the way the House annual index is — this is the date the
    report was *filed*, not necessarily the disclosure period it covers (a
    January filing can report prior-year transactions), so bronze's `year=`
    partition is filed-year, an approximation good enough for idempotent
    storage but worth remembering if a later stage assumes it's the
    transaction year.
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
