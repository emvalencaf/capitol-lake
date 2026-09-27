"""Classifying a fetched Senate eFD response as cleared, blocked, or ambiguous.

Pure, unit-tested pieces of the Senate eFD Akamai-clearance mechanics,
shared between `senate_collect_automated` (the real Playwright session
driver, `senate_collect_automated.browser_session`) and `senate_akamai_probe`
(the throwaway Lambda-origin probe that answered whether a Lambda egress IP
clears the eFD Akamai check, #29). Kept separate from
`senate_collect_automated`'s own browser-session module so the probe's image
doesn't need Playwright's `run_senate_efd_session` at all — only this
classification logic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

# Confirmed live (#23, docs/local-dev.md): a cleared filing request lands on
# the filing's own print view, titled exactly this.
CLEARED_FILING_TITLE_MARKER = "eFD: Print Periodic Transaction Report"

# Akamai's own block page (Bot Manager / Kona Site Defender default) always
# carries one of these — a "Reference #<digits>.<hex>" incident id and/or the
# literal "Access Denied" heading. Either alone is enough to call it Akamai,
# distinct from some other, non-Akamai failure (timeout, 5xx, DNS).
_AKAMAI_MARKERS = ("Access Denied", "Reference #")

# `channel="chromium"` forces the classic full-Chromium headless mode
# (Playwright >=1.45 otherwise launches a separate "Chromium Headless Shell"
# binary a plain `playwright install chromium` doesn't download); the launch
# args are the ones a Lambda container's sandbox needs (no kernel sandbox
# capabilities, no GPU, no meaningful /dev/shm) per
# microsoft/playwright#14023. Shared between `senate_collect_automated` and
# `senate_akamai_probe`, which launch the same way for the same reason.
#
# `--disable-blink-features=AutomationControlled` (#68): without it,
# `navigator.webdriver` reads `true`. By itself this flag isn't confirmed to
# affect Akamai's check either way (#68's own hand test cleared the check
# with `webdriver` still `true`, once the UA fix below was applied) — it's
# kept as a cheap, standard headless-detection precaution against a future,
# stricter check, not because this one is known to read it.
LAMBDA_SAFE_CHROMIUM_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--single-process",
    "--disable-blink-features=AutomationControlled",
]


def de_headless_user_agent(browser) -> str:
    """A real desktop Chrome's UA never contains "Headless" the way
    Playwright's classic headless Chromium's default UA does
    (`HeadlessChrome/<version>` instead of `Chrome/<version>`) — confirmed by
    hand (#68) as the one fingerprint signal Akamai's check actually keys
    off: the same request, only this substring changed, went from 403 to
    200, independent of `navigator.webdriver`'s value. Derived from
    `browser.version` rather than a hardcoded version string, so it never
    drifts from whichever Chromium build is actually installed.
    """
    return (
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{browser.version} Safari/537.36"
    )


ResponseOutcome = Literal["cleared", "blocked_akamai", "blocked_other", "ambiguous"]


def classify_response(
    status_code: int, body: str, *, is_cleared: Callable[[str], bool]
) -> ResponseOutcome:
    """Classify one fetched response as cleared, blocked, or ambiguous.

    Shared shape for every response a Senate eFD session classifies (the
    search page's own load and each filing fetch), parameterized by
    `is_cleared` since what counts as "the real thing came back" differs per
    response (a filing's print-view title vs. the search endpoint's own JSON
    shape):

    - `"cleared"`: HTTP 200 and `is_cleared(body)` — the Akamai check passed
      and this really is the expected content, not just any 200.
    - `"blocked_akamai"`: HTTP 403 with an Akamai block-page marker present,
      or HTTP 403 with an empty/near-empty body (Akamai's block sometimes
      serves no HTML at all, just the status) — matches #17/#23's prior
      confirmed-live Akamai 403 shape.
    - `"blocked_other"`: any other non-200 status, or a 200 that isn't the
      expected content (e.g. a login/agreement redirect target) — a real
      failure, but not evidence either way about the Akamai fingerprint
      check specifically.
    - `"ambiguous"`: 200 status but the body matches neither the cleared nor
      a recognizable blocked shape — needs a human to look at the captured
      body rather than trust an automatic classification.
    """
    if status_code == 200:
        return "cleared" if is_cleared(body) else "ambiguous"
    if status_code == 403:
        stripped = body.strip()
        if not stripped or any(marker in body for marker in _AKAMAI_MARKERS):
            return "blocked_akamai"
        return "blocked_other"
    return "blocked_other"


def classify_probe_result(status_code: int, html: str) -> ResponseOutcome:
    """Classify a filing-fetch response."""
    return classify_response(
        status_code, html, is_cleared=lambda html: CLEARED_FILING_TITLE_MARKER in html
    )
