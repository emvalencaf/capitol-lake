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
below rate-limits the individual filing fetches (~1 request/second) and
drives the chamber-agnostic `bronze_write` contract, exactly as
`house_collect` does. Network and S3 access are injected as callables, so
this is testable with no live network call; only `senate_collect.handler`
wires it to a real HTTP client.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from shared.bronze_write import bronze_write
from shared.keys import bronze_key, bronze_meta_key
from shared.senate_index import RateLimiter, parse_senate_index, senate_filing_url


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
