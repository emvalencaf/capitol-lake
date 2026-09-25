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
    """One probe run's outcome, in the shape recorded in the research doc."""

    filing_id: str
    status_code: int
    outcome: ProbeOutcome
    html_excerpt: str


def run_probe(filing_id: str, *, url_template: str) -> ProbeResult:
    """Drive a real headless-Chromium request at one `/ptr/` filing via Playwright.

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
            response = page.goto(url, wait_until="networkidle")
            status_code = response.status if response is not None else 0
            html = page.content()
        finally:
            browser.close()

    outcome = classify_probe_result(status_code, html)
    return ProbeResult(
        filing_id=filing_id,
        status_code=status_code,
        outcome=outcome,
        html_excerpt=html[:2000],
    )
