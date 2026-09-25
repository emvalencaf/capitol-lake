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

Only `classify_probe_result` is a pure function and unit-tested; `run_probe`
drives a real Playwright browser against the live site and is exercised by
hand, the same convention `handlers/*_handler.py` follows for real network
calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Confirmed live (#23, docs/local-dev.md): a cleared request lands on the
# filing's own print view, titled exactly this.
CLEARED_TITLE_MARKER = "eFD: Print Periodic Transaction Report"

# #23's own probe target — visited first (see module docstring) so the
# browser has a normal navigation history/session before requesting a
# filing, same as every real local run this repo has on record.
SENATE_HOME_URL = "https://efdsearch.senate.gov/search/home/"

# Akamai's own block page (Bot Manager / Kona Site Defender default) always
# carries one of these — a "Reference #<digits>.<hex>" incident id and/or the
# literal "Access Denied" heading. Either alone is enough to call it Akamai,
# distinct from some other, non-Akamai failure (timeout, 5xx, DNS).
_AKAMAI_MARKERS = ("Access Denied", "Reference #")

ProbeOutcome = Literal["cleared", "blocked_akamai", "blocked_other", "ambiguous"]


def classify_probe_result(status_code: int, html: str) -> ProbeOutcome:
    """Classify one fetched `/ptr/` response as cleared, blocked, or ambiguous.

    - `"cleared"`: HTTP 200 and the page is the actual filing print view
      (`CLEARED_TITLE_MARKER` in the title) — the Akamai check passed.
    - `"blocked_akamai"`: HTTP 403 with an Akamai block-page marker present,
      or HTTP 403 with an empty/near-empty body (Akamai's block sometimes
      serves no HTML at all, just the status) — matches #17/#23's prior
      confirmed-live Akamai 403 shape.
    - `"blocked_other"`: any other non-200 status, or a 200 that isn't the
      filing page (e.g. a login/agreement redirect target) — a real failure,
      but not evidence either way about the Akamai fingerprint check
      specifically.
    - `"ambiguous"`: 200 status but the body matches neither the cleared nor
      a recognizable blocked shape — needs a human to look at the captured
      HTML rather than trust an automatic classification.
    """
    if status_code == 200:
        if CLEARED_TITLE_MARKER in html:
            return "cleared"
        return "ambiguous"
    if status_code == 403:
        stripped = html.strip()
        if not stripped or any(marker in html for marker in _AKAMAI_MARKERS):
            return "blocked_akamai"
        return "blocked_other"
    return "blocked_other"


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
    from playwright.sync_api import sync_playwright

    url = url_template.format(filing_id=filing_id)

    with sync_playwright() as playwright:
        # `channel="chromium"` forces the classic full-Chromium headless
        # mode: Playwright >=1.45 defaults headless launches to a separate
        # "Chromium Headless Shell" binary that a plain `playwright install
        # chromium` (docker/senate_akamai_probe.Dockerfile) doesn't
        # download, which fails with "Executable doesn't exist ...
        # chromium_headless_shell..." otherwise.
        # Lambda's container sandbox lacks Chromium's usual kernel sandbox
        # capabilities, a GPU, and any meaningful /dev/shm size — launching
        # without these flags is a well-documented failure mode there
        # (microsoft/playwright#14023: prctl(PR_SET_NO_NEW_PRIVS) failures,
        # GPU process crash-loops, eventual launch timeout).
        browser = playwright.chromium.launch(
            channel="chromium",
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--single-process",
            ],
        )
        try:
            page = browser.new_page()

            home_response = page.goto(SENATE_HOME_URL, wait_until="networkidle")
            home_status_code = home_response.status if home_response is not None else 0

            # A plain Locator.check() hung indefinitely (30s timeout) here on
            # a real Lambda run: Playwright's actionability engine waits out
            # any navigation the click triggers as part of the click itself,
            # and that wait never resolved in this environment — plausibly
            # interacting badly with --single-process. Setting the checkbox
            # and submitting its form purely via JS sidesteps Playwright's
            # click-driven navigation wait entirely; only the explicit
            # `wait_for_load_state` below waits for the resulting page.
            agreement_accepted = False
            if page.locator(_AGREEMENT_CHECKBOX_SELECTOR).count() > 0:
                page.evaluate(
                    """() => {
                        const cb = document.querySelector('input[name="prohibition_agreement"]');
                        cb.checked = true;
                        cb.form.submit();
                    }"""
                )
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
