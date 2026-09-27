"""One authenticated Playwright session driving the full Senate eFD PTR flow.

#28 (Senate collector automation) resolved on a headless-Playwright
collection step; #29 confirmed a Lambda-origin request clears the eFD
Akamai check, provided the automation replicates the site's real access
flow (warm-up navigation, accept the `prohibition_agreement` gate via a
real trusted click, then request filings) — see
`docs/research/senate-akamai-lambda-probe.md` and
`senate_akamai_probe/probe.py`'s module docstring for how that was learned.
A fingerprint signal independent of network origin also turned out to
matter (#68, confirmed by hand from a network #23/#29 already cleared,
which still 403'd until this was fixed): the default headless UA string's
`HeadlessChrome` substring — see `shared.senate_efd_classification`'s
`LAMBDA_SAFE_CHROMIUM_LAUNCH_ARGS`/`de_headless_user_agent`.

This module is the pure-mechanics layer #67 scopes: one browser session
that warms up, accepts the agreement, submits the PTR search form for a
7-day lookback window, feeds the resulting DataTables JSON through
`shared.senate_index.parse_senate_index`, fetches each entry via a real page
navigation in the *same* session (cookie reuse alone doesn't clear Akamai —
see `senate_collect.collect`'s module docstring), and writes each
successfully fetched filing through `bronze_write`, exactly as
`collect_senate` does. No Lambda handler, no infra, no Docker yet (later
tickets) — this is runnable and demoable by hand against the live site, the
same convention `senate_akamai_probe/probe.py` and every `*/handler.py`
follow: real network/browser driving isn't unit-tested, only the pure
pieces are (the classification logic in `shared.senate_efd_classification`,
and `search_date_window`).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from shared.bronze_write import bronze_write
from shared.keys import bronze_key
from shared.senate_efd_classification import (
    LAMBDA_SAFE_CHROMIUM_LAUNCH_ARGS,
    ResponseOutcome,
    classify_probe_result,
    classify_response,
    de_headless_user_agent,
)
from shared.senate_index import RateLimiter, SenateIndexEntry, parse_senate_index, senate_filing_url

SENATE_HOME_URL = "https://efdsearch.senate.gov/search/home/"

# The site's own Django-backed search gate (independent of Akamai): GET the
# home page for a CSRF cookie, check this box, submit — the response sets
# the session's search_agreement flag, redirecting to /search/. Confirmed
# field name via public prior-art scrapers of this exact site (not guessed).
_AGREEMENT_CHECKBOX_SELECTOR = 'input[name="prohibition_agreement"]'

# PTR search form fields, confirmed live against the site (#67).
_PTR_REPORT_TYPE_SELECTOR = 'input[name="report_type"][value="11"]'
_FROM_DATE_SELECTOR = 'input#fromDate[name="submitted_start_date"]'
_TO_DATE_SELECTOR = 'input#toDate[name="submitted_end_date"]'
_SEARCH_SUBMIT_SELECTOR = 'button:has-text("Search Reports")'

# The eFD search UI's own DataTables endpoint (see `senate_collect.collect`'s
# module docstring) — matched substring, not the full URL, since Playwright's
# `expect_response` predicate only needs to disambiguate it from the page's
# other requests (analytics, static assets, ...).
_SEARCH_DATA_URL_MARKER = "/search/report/data/"

_DATE_FORMAT = "%m/%d/%Y"
LOOKBACK_DAYS = 7

# Any overflow past this many filings in one run is left for the next
# scheduled run — `bronze_write`'s hash-gate makes re-searching the overlap
# free (#67).
MAX_FILINGS_PER_RUN = 300


def _is_cleared_search_response(body: str) -> bool:
    """A cleared PTR search response is JSON with a `data` list `parse_senate_index` can read."""
    try:
        payload = json.loads(body)
    except ValueError:
        return False
    return isinstance(payload.get("data"), list)


def classify_search_response(status_code: int, body: str) -> ResponseOutcome:
    """Classify the PTR search form's own DataTables JSON response."""
    return classify_response(status_code, body, is_cleared=_is_cleared_search_response)


def search_date_window(today: date) -> tuple[str, str]:
    """`(from_date, to_date)` strings in `MM/DD/YYYY`, a `LOOKBACK_DAYS`-day window ending today."""
    from_date = today - timedelta(days=LOOKBACK_DAYS)
    return from_date.strftime(_DATE_FORMAT), today.strftime(_DATE_FORMAT)


def filings_to_fetch(entries: list[SenateIndexEntry], max_filings: int) -> list[SenateIndexEntry]:
    """Cap `entries` at `max_filings`; overflow is left for the next scheduled run (#67).

    `bronze_write`'s hash-gate makes re-searching the same overlap on that
    next run free, so dropping the tail here rather than raising is safe.
    """
    return entries[:max_filings]


class SenateEfdBlockedError(RuntimeError):
    """A classified response in this session came back as anything but `"cleared"`.

    Raised immediately, the first time it happens (#67: no retry/backoff
    tolerance) — carries enough context (`outcome`, `status_code`,
    `final_url`) to diagnose from a Lambda log later, without needing the
    full captured body. Filings already written to bronze before this
    raises stay written; there is no rollback.
    """

    def __init__(self, *, context: str, outcome: ResponseOutcome, status_code: int, final_url: str):
        self.context = context
        self.outcome = outcome
        self.status_code = status_code
        self.final_url = final_url
        super().__init__(
            f"Senate eFD session blocked while {context}: outcome={outcome!r}, "
            f"status_code={status_code}, final_url={final_url!r}"
        )


@dataclass(frozen=True)
class SenateEfdSessionResult:
    """One `run_senate_efd_session` run's outcome, in `collect_senate`'s shape plus counts."""

    years: list[int]
    written: list[str]
    skipped: list[str]
    filings_available: int
    filings_processed: int


def run_senate_efd_session(
    *,
    known_doc_ids: Callable[[], set[str]],
    write_bytes: Callable[[str, bytes], None],
    now: Callable[[], str],
    today: Callable[[], date] = date.today,
    rate_limiter: RateLimiter | None = None,
    max_filings: int = MAX_FILINGS_PER_RUN,
    on_progress: Callable[[dict], None] | None = None,
) -> SenateEfdSessionResult:
    """Drive one authenticated Playwright session through the full Senate eFD PTR flow.

    Warms up on `SENATE_HOME_URL`, accepts the `prohibition_agreement` gate
    via a real trusted `.click()` (a synthetic-event submit was already
    proven to get rejected — see `senate_akamai_probe/probe.py`'s module
    docstring), submits the PTR search form for a `LOOKBACK_DAYS`-day
    window, classifies that search response, and — if cleared — fetches up
    to `max_filings` of the resulting `/ptr/` entries via a real page
    navigation each (rate-limited by `rate_limiter`, ~1 req/s by default),
    classifying and writing each through `bronze_write` as it goes. Any
    overflow past `max_filings` is left for the next scheduled run.

    Raises `SenateEfdBlockedError` immediately on the first response (the
    search page's own load, or any filing fetch) that classifies as
    anything but `"cleared"`; filings already written to bronze before that
    stay written. `known_doc_ids()` is called once, before the fetch loop,
    to get every filing UUID already on record; an entry whose UUID is
    already known is skipped with **no page navigation at all** — no
    fetch, no rate-limit charged, no Akamai classification needed for it
    (ADR-0018, same policy `collect_house`/`collect_senate` apply — *not*
    backed by primary-source research for Senate specifically; see
    `collect_senate`'s docstring for the caveat). Storage access is injected
    (`known_doc_ids`, `write_bytes`, `now`) the same way `collect_senate`
    injects it, but the browser session itself is not — driving a real
    Playwright browser against the live site isn't unit-tested, only
    exercised by hand, the same convention `senate_akamai_probe.probe.run_probe`
    follows.

    `on_progress`, if given, is called after every entry with `{"index": i,
    "total": len(entries_to_fetch), "doc_id": ..., "action": "write" |
    "skip"}` (1-based `index`, `doc_id` here is the filing's UUID) — a hook
    for the handler to surface progress on a run that can take minutes.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    rate_limiter = rate_limiter or RateLimiter()
    from_date, to_date = search_date_window(today())

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chromium", args=LAMBDA_SAFE_CHROMIUM_LAUNCH_ARGS
        )
        try:
            page = browser.new_page(user_agent=de_headless_user_agent(browser))

            home_response = page.goto(SENATE_HOME_URL, wait_until="networkidle")
            home_status_code = home_response.status if home_response is not None else 0

            if page.locator(_AGREEMENT_CHECKBOX_SELECTOR).count() > 0:
                try:
                    page.locator(_AGREEMENT_CHECKBOX_SELECTOR).click(timeout=10_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_load_state("networkidle")

            # A blocked/agreement-rejected session never reaches the search
            # form at all — the site just re-serves its home/block page, so
            # these locators would otherwise hang for each field's full
            # default timeout before failing. Bounding them lets a bad
            # warm-up surface as a classified `SenateEfdBlockedError`
            # (using the home page's own response, the best evidence
            # available at this point) rather than a raw Playwright timeout.
            try:
                page.locator(_PTR_REPORT_TYPE_SELECTOR).check(timeout=10_000)
                page.locator(_FROM_DATE_SELECTOR).fill(from_date, timeout=10_000)
                page.locator(_TO_DATE_SELECTOR).fill(to_date, timeout=10_000)
            except PlaywrightTimeoutError:
                # Reuses the filing-page classifier here as a diagnostic
                # fallback, not because this really is a filing response: at
                # this point we already know something failed, so its
                # `"cleared"` branch (the filing print-view title) simply
                # never matches — only its blocked-vs-ambiguous shape
                # (Akamai markers vs. an unrecognized body) matters here.
                raise SenateEfdBlockedError(
                    context="reaching the PTR search form after warm-up",
                    outcome=classify_probe_result(home_status_code, page.content()),
                    status_code=home_status_code,
                    final_url=page.url,
                ) from None

            with page.expect_response(
                lambda response: _SEARCH_DATA_URL_MARKER in response.url
            ) as search_response_info:
                page.locator(_SEARCH_SUBMIT_SELECTOR).click()
            search_response = search_response_info.value
            search_status_code = search_response.status
            search_body = search_response.text()

            search_outcome = classify_search_response(search_status_code, search_body)
            if search_outcome != "cleared":
                raise SenateEfdBlockedError(
                    context="submitting the PTR search form",
                    outcome=search_outcome,
                    status_code=search_status_code,
                    final_url=page.url,
                )

            entries: list[SenateIndexEntry] = parse_senate_index(json.loads(search_body))
            entries_to_fetch = filings_to_fetch(entries, max_filings)
            total = len(entries_to_fetch)
            existing_doc_ids = known_doc_ids()

            written: list[str] = []
            skipped: list[str] = []
            for index, entry in enumerate(entries_to_fetch, start=1):
                if entry.filing_id in existing_doc_ids:
                    skipped.append(bronze_key("senate", entry.year, entry.filing_id, "html"))
                    action = "skip"
                else:
                    rate_limiter.wait()

                    url = senate_filing_url(entry.filing_id)
                    filing_response = page.goto(url, wait_until="networkidle")
                    status_code = filing_response.status if filing_response is not None else 0
                    html = page.content()

                    outcome = classify_probe_result(status_code, html)
                    if outcome != "cleared":
                        raise SenateEfdBlockedError(
                            context=f"fetching filing {entry.filing_id}",
                            outcome=outcome,
                            status_code=status_code,
                            final_url=page.url,
                        )

                    candidate_bytes = html.encode("utf-8")
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
        finally:
            browser.close()

    return SenateEfdSessionResult(
        years=sorted({e.year for e in entries_to_fetch}),
        written=written,
        skipped=skipped,
        filings_available=len(entries),
        filings_processed=len(entries_to_fetch),
    )
