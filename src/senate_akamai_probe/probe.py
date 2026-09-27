"""Throwaway probe: does a Lambda-origin headless-Playwright request clear
the Senate eFD `/ptr/` Akamai check the way #23's local-network probe did?

This is **not** a pipeline stage (see `docs/local-dev.md`'s stage/handler
convention) — it exists only to answer the open question #29 raises: #23
confirmed a headless-Chromium request clears the Akamai bot/fingerprint
block from a *local/dev network*; whether the same holds from an actual AWS
Lambda egress IP is untested, and #28's Senate-automation design is
contingent on the answer. Run this once from a real Lambda invocation
(`infra/probes/senate-akamai-probe/`, not wired into the main stack), record
the result in `docs/research/senate-akamai-lambda-probe.md`, then tear the
probe infra down — it has no ongoing purpose once the question is answered.

`run_probe` first navigates to `SENATE_HOME_URL` before the target filing,
in the *same* browser page/context — replicating what #23's and #35's real
local runs actually did (both describe "navigating"/"a Selenium-established
session" before fetching a filing, never a single cold request straight at
a filing URL). A first Lambda-origin attempt that skipped this warm-up
landed on `/search/home/` instead of the filing — the same URL #23's own
*successful* local run first landed on too, before that run's session had
been used for anything else — so a single cold request isn't actually
evidence of a Lambda-specific block; it may just be this site's ordinary
behavior for a browser that hasn't loaded anything yet.

A second, warmed-up run (visiting `SENATE_HOME_URL` before the filing, still
one navigation each) *also* landed back on `/search/home/`. The site itself
gates its Django-backed search behind a `prohibition_agreement` checkbox on
that page — `GET /search/home/` for a CSRF cookie, then
`POST prohibition_agreement=1` to the same URL, which redirects to `/search/`
with the session's `search_agreement` flag set — a requirement independent
of Akamai's bot/fingerprint check. `run_probe` now also checks that checkbox
and submits the form before requesting the filing, matching the site's
actual access flow rather than assuming a bare page load is enough.

`classify_probe_result` moved permanently to
`shared.senate_efd_classification` (#67, the shared module that now backs
the full authenticated flow this probe only ever answered one question
about) and is re-exported here unchanged so this probe's own call site and
any existing caller keep working. Only that function is a pure,
unit-tested one; `run_probe` drives a real Playwright browser against the
live site and is exercised by hand, the same convention
`*/handler.py` follows for real network calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.senate_efd_classification import (
    CLEARED_FILING_TITLE_MARKER as CLEARED_TITLE_MARKER,
)
from shared.senate_efd_classification import (
    LAMBDA_SAFE_CHROMIUM_LAUNCH_ARGS,
    classify_probe_result,
    de_headless_user_agent,
)
from shared.senate_efd_classification import (
    ResponseOutcome as ProbeOutcome,
)

__all__ = [
    "CLEARED_TITLE_MARKER",
    "SENATE_HOME_URL",
    "ProbeOutcome",
    "ProbeResult",
    "classify_probe_result",
    "de_headless_user_agent",
    "run_probe",
]

# #23's own probe target — visited first (see module docstring) so the
# browser has a normal navigation history/session before requesting a
# filing, same as every real local run this repo has on record.
SENATE_HOME_URL = "https://efdsearch.senate.gov/search/home/"


@dataclass(frozen=True)
class ProbeResult:
    """One probe run's outcome, in the shape recorded in the research doc.

    `final_url` is `page.url` after `goto` settles — Playwright follows
    redirects transparently, so `status_code` alone is the *final* response's
    status and doesn't reveal that a redirect happened at all. A block or
    gate shaped as a redirect (e.g. to the site's own homepage or a
    login/agreement page) reads as an unremarkable 200 without this: compare
    `final_url` against the requested filing URL to tell "landed elsewhere"
    from "this really is what a cleared request returns".

    `post_agreement_url` is `page.url` right after the agreement form
    submits, *before* the filing is ever requested — it disambiguates two
    otherwise-identical-looking failures: the agreement submission itself
    landing back on `SENATE_HOME_URL` (the site rejected/ignored it) versus
    it succeeding (landing on `/search/`) but the filing request afterward
    losing that session and bouncing back to `SENATE_HOME_URL` on its own.
    """

    filing_id: str
    status_code: int
    outcome: ProbeOutcome
    final_url: str
    html_excerpt: str
    home_status_code: int
    agreement_accepted: bool
    post_agreement_url: str


# The site's own Django-backed search gate (independent of Akamai): GET this
# page for a CSRF cookie, check this box, submit — the response sets the
# session's search_agreement flag, redirecting to /search/. Confirmed field
# name via public prior-art scrapers of this exact site (not guessed).
_AGREEMENT_CHECKBOX_SELECTOR = 'input[name="prohibition_agreement"]'


def run_probe(filing_id: str, *, url_template: str) -> ProbeResult:
    """Drive a real headless-Chromium request at one `/ptr/` filing via Playwright.

    Navigates to `SENATE_HOME_URL`, accepts the site's own
    `prohibition_agreement` checkbox gate, then requests the filing — all in
    the same page/session, replicating what #23/#35's local runs actually
    did rather than a single cold request (see the module docstring).
    `home_status_code` is the warm-up navigation's own status (a block there
    is a materially harder finding than the filing request alone landing
    back on it); `agreement_accepted` records whether the checkbox was found
    and submitted at all — `False` means the flow itself didn't work as
    expected (site markup changed, or the interaction was blocked/prevented
    some other way), which is itself worth knowing before trusting
    `outcome`.

    Requires the `playwright` package and its Chromium browser download,
    both installed by `docker/senate_akamai_probe.Dockerfile` — not a
    dependency of the main pipeline (`pyproject.toml` deliberately excludes
    it), since this probe is throwaway infra, not a stage. Imports
    `playwright.sync_api` lazily so importing this module (e.g. from a test
    that only exercises `classify_probe_result`) never requires the package
    to be installed.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    url = url_template.format(filing_id=filing_id)

    with sync_playwright() as playwright:
        # Same Lambda-safe launch shape `senate_collect_automated/browser_session.py`
        # shares this constant for — see its own comment for why each flag
        # is needed.
        browser = playwright.chromium.launch(
            channel="chromium", args=LAMBDA_SAFE_CHROMIUM_LAUNCH_ARGS
        )
        try:
            page = browser.new_page(user_agent=de_headless_user_agent(browser))

            home_response = page.goto(SENATE_HOME_URL, wait_until="networkidle")
            home_status_code = home_response.status if home_response is not None else 0

            # Locator.check() hung for the full 30s timeout on a real Lambda
            # run, but its own log showed the click and the resulting
            # navigation both completing ("click action done", "navigations
            # have finished") — check() hangs *after* that, re-verifying the
            # checkbox is still checked, which can never succeed once the
            # click's own onchange handler has already navigated the page
            # away (the original element is detached). A JS-only submit
            # (checked=true; form.submit()) avoided that hang but got
            # rejected — plausibly because it fires a synthetic, untrusted
            # DOM event (event.isTrusted: false), a signal some bot defenses
            # check for, unlike a real click. `.click()` (not `.check()`)
            # performs a genuine, trusted click without that unreachable
            # post-condition, so it shouldn't hang the same way `.check()`
            # did — but tolerate a timeout anyway, since the click and its
            # navigation may already have succeeded by the time it fires.
            agreement_accepted = False
            if page.locator(_AGREEMENT_CHECKBOX_SELECTOR).count() > 0:
                try:
                    page.locator(_AGREEMENT_CHECKBOX_SELECTOR).click(timeout=10_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_load_state("networkidle")
                agreement_accepted = True

            post_agreement_url = page.url

            response = page.goto(url, wait_until="networkidle")
            status_code = response.status if response is not None else 0
            final_url = page.url
            html = page.content()
        finally:
            browser.close()

    outcome = classify_probe_result(status_code, html)
    return ProbeResult(
        filing_id=filing_id,
        status_code=status_code,
        outcome=outcome,
        final_url=final_url,
        html_excerpt=html[:2000],
        home_status_code=home_status_code,
        agreement_accepted=agreement_accepted,
        post_agreement_url=post_agreement_url,
    )
