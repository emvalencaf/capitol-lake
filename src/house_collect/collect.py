"""House collector: pure decision logic for the annual PTR index.

Parses the House Clerk's annual index ZIP, routes each filing by its
document-id prefix (`shared.doc_id.route_doc_id`), skips a `doc_id` already
on record with no fetch at all (see `collect_house`'s docstring for why
that's safe), rate-limits the fetch loop for everything else, and drives the
chamber-agnostic `bronze_write` contract. All network and S3 access is
injected as callables into `collect_house`, so index parsing, the known-
doc-id set, and rate limiting are all testable with no live network call and
no real S3; only `house_collect.handler` wires this to real HTTP and a real
S3 listing.
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO

from shared.bronze_write import bronze_write
from shared.doc_id import UnknownDocIdPrefixError, route_doc_id
from shared.keys import bronze_key

# The House Clerk's Financial Disclosure site serves every PTR (digital or
# scanned) under the same annual path; only the doc-id prefix distinguishes
# them. Confirm against a recorded index before a first production run.
HOUSE_INDEX_URL_TEMPLATE = (
    "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
)
HOUSE_FILING_URL_TEMPLATE = (
    "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
)

PTR_FILING_TYPE = "P"


def house_index_url(year: int) -> str:
    """Source URL for a given year's annual House index ZIP."""
    return HOUSE_INDEX_URL_TEMPLATE.format(year=year)


def house_filing_url(doc_id: str, year: int) -> str:
    """Source URL for a filing's PDF bytes."""
    return HOUSE_FILING_URL_TEMPLATE.format(year=year, doc_id=doc_id)


@dataclass(frozen=True)
class HouseIndexEntry:
    """One routed row from the annual House index."""

    doc_id: str
    year: int
    kind: str  # "digital" or "scanned"
    index_row: int


def parse_house_index(zip_bytes: bytes, year: int) -> list[HouseIndexEntry]:
    """Parse the annual House ZIP index into routed PTR filing entries.

    The ZIP holds a single XML member with one `<Member>` element per
    filing; only `FilingType == "P"` (Periodic Transaction Report) rows are
    kept, and rows whose `DocID` doesn't match a known routing prefix are
    skipped rather than raised, since the index also lists filing types
    this collector doesn't handle.
    """
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        xml_names = [name for name in zf.namelist() if name.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("House index ZIP has no XML member")
        xml_bytes = zf.read(xml_names[0])

    root = ET.fromstring(xml_bytes)
    entries = []
    for row, member in enumerate(root.findall("Member")):
        if (member.findtext("FilingType") or "").strip() != PTR_FILING_TYPE:
            continue
        doc_id = (member.findtext("DocID") or "").strip()
        if not doc_id:
            continue
        try:
            kind = route_doc_id(doc_id)
        except UnknownDocIdPrefixError:
            continue
        entries.append(HouseIndexEntry(doc_id=doc_id, year=year, kind=kind, index_row=row))
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


def collect_house(
    year: int,
    *,
    fetch_index: Callable[[str], bytes],
    fetch_filing: Callable[[str], bytes],
    known_doc_ids: Callable[[], set[str]],
    write_bytes: Callable[[str, bytes], None],
    now: Callable[[], str],
    rate_limiter: RateLimiter | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Collect one year of House PTR filings into bronze.

    Fetches the annual index via `fetch_index(url)`, calls `known_doc_ids()`
    *once* to get every `doc_id` already on record, then for each routed
    entry checks membership in that set *before* touching the network: a
    known `doc_id` is trusted as immutable and skipped with no
    `fetch_filing` call at all, no `rate_limiter.wait()` charged against it,
    and no re-hash (ADR-0018 — `known_doc_ids` is a single listing, not one
    read per entry, since the write path below never needs a prior hash
    value, only whether one exists). Only a `doc_id` never seen before gets
    fetched (rate-limited by `rate_limiter`, ~1 request/second by default)
    and written through `bronze_write`, which will therefore always plan a
    `"write"` for it (`existing_sha256` is `None` by construction on this
    path — there is nothing to hash-compare against).

    This trades away detecting a same-`doc_id` content correction after the
    fact — `docs/research/house-ptr-amendment-doc-id-behavior.md` found, with
    high confidence from the House Clerk's own PTR form/instructions and a
    full year's live index, that a correction is filed and indexed as a
    brand-new `DocID`, never a same-`DocID` overwrite, though no primary
    source states that as an absolute guarantee. If that assumption ever
    turns out wrong for some `doc_id`, this collector will keep serving the
    stale bronze copy indefinitely for it, with no automatic way to notice.

    Network and storage access are fully injected so this function runs
    against fakes in tests, with no live network call and no real S3.

    `on_progress`, if given, is called after every entry with
    `{"index": i, "total": len(entries), "doc_id": ..., "action": "write" |
    "skip"}` (1-based `index`) — a hook for the handler to surface progress
    on a run that can take minutes, not a logging concern of this pure
    function's own.
    """
    rate_limiter = rate_limiter or RateLimiter()
    entries = parse_house_index(fetch_index(house_index_url(year)), year)
    total = len(entries)
    existing_doc_ids = known_doc_ids()

    written: list[str] = []
    skipped: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if entry.doc_id in existing_doc_ids:
            skipped.append(bronze_key("house", entry.year, entry.doc_id, "pdf"))
            action = "skip"
        else:
            rate_limiter.wait()

            url = house_filing_url(entry.doc_id, entry.year)
            candidate_bytes = fetch_filing(url)

            plan = bronze_write(
                chamber="house",
                year=entry.year,
                doc_id=entry.doc_id,
                ext="pdf",
                candidate_bytes=candidate_bytes,
                existing_sha256=None,
                source_url=url,
                fetched_at=now(),
                index_row=entry.index_row,
            )

            meta = {**plan["meta"], "kind": entry.kind}
            write_bytes(plan["key"], candidate_bytes)
            write_bytes(plan["meta_key"], json.dumps(meta).encode("utf-8"))
            written.append(plan["key"])
            action = "write"

        if on_progress is not None:
            on_progress({"index": index, "total": total, "doc_id": entry.doc_id, "action": action})

    return {"year": year, "written": written, "skipped": skipped}
