"""Senate collector: drives the manual/local `/ptr/` eFD collection path.

The Senate eFD search UI is Akamai bot/fingerprint-protected (#17, #23): a
plain scripted request (no JS engine, no browser TLS/header fingerprint) 403s
even against the individual `/ptr/` filing pages, confirmed live — only a
real browser engine (headless Chromium via Selenium, reusing session cookies
does *not* help a plain HTTP client) gets through. Per #18, this collector
therefore stays out of the automated cloud pipeline and is run locally by a
human (or a local headless-browser step) that completes the site's
agreement flow and captures results; `response` here is that
already-captured JSON body from the eFD search UI's own DataTables endpoint
(`POST /search/report/data/`) — this module never scripts the search
itself. Index parsing/routing lives in `shared.senate_index` (also used by
`senate_collect_automated` and `senate_akamai_probe`); `collect_senate`
below skips a `filing_id` already on record with no fetch at all (ADR-0018,
same policy `collect_house` applies to House), rate-limits the fetch loop
for everything else (~1 request/second), and drives the chamber-agnostic
`bronze_write` contract, exactly as `house_collect` does. Network and S3
access are injected as callables, so this is testable with no live network
call; only `senate_collect.handler` wires it to a real HTTP client.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from shared.bronze_write import bronze_write
from shared.keys import bronze_key
from shared.senate_index import RateLimiter, parse_senate_index, senate_filing_url


def collect_senate(
    response: dict,
    *,
    fetch_filing: Callable[[str], bytes],
    known_doc_ids: Callable[[], set[str]],
    write_bytes: Callable[[str, bytes], None],
    now: Callable[[], str],
    rate_limiter: RateLimiter | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    """Collect the `/ptr/` filings in a captured Senate eFD search response into bronze.

    Routes and filters `response` to `/ptr/` entries via `parse_senate_index`,
    calls `known_doc_ids()` *once* to get every filing UUID already on
    record, then for each entry checks membership in that set *before*
    touching the network: a known UUID is trusted as immutable and skipped
    with no `fetch_filing` call at all and no `rate_limiter.wait()` charged
    against it (ADR-0018 — unlike House, this is *not* backed by
    primary-source research confirming a Senate eFD amendment always gets
    its own separate UUID; that assumption comes only from this repo's own
    prior reading of the site's behavior, unverified independently. If it
    ever turns out wrong for some UUID, this collector will keep serving the
    stale bronze copy for it indefinitely, with no automatic way to notice).
    Only a UUID never seen before gets fetched (rate-limited by
    `rate_limiter`, ~1 request/second by default) and written through
    `bronze_write`, which will therefore always plan a `"write"` for it.
    Network and storage access are fully injected so this function runs
    against fakes in tests, with no live network call and no real S3.

    `on_progress`, if given, is called after every entry with
    `{"index": i, "total": len(entries), "doc_id": ..., "action": "write" |
    "skip"}` (1-based `index`, `doc_id` here is the filing's UUID) — a hook
    for the handler to surface progress on a run that can take minutes, not
    a logging concern of this pure function's own.
    """
    rate_limiter = rate_limiter or RateLimiter()
    entries = parse_senate_index(response)
    total = len(entries)
    existing_doc_ids = known_doc_ids()

    written: list[str] = []
    skipped: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if entry.filing_id in existing_doc_ids:
            skipped.append(bronze_key("senate", entry.year, entry.filing_id, "html"))
            action = "skip"
        else:
            rate_limiter.wait()

            url = senate_filing_url(entry.filing_id)
            candidate_bytes = fetch_filing(url)

            plan = bronze_write(
                chamber="senate",
                year=entry.year,
                doc_id=entry.filing_id,
                ext="html",
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
            on_progress(
                {
                    "index": index,
                    "total": total,
                    "doc_id": entry.filing_id,
                    "action": action,
                }
            )

    return {"years": sorted({e.year for e in entries}), "written": written, "skipped": skipped}
