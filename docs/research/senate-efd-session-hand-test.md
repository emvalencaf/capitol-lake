# Senate eFD PTR search-and-fetch session: hand test (#67)

## What was run

`capitol_lake.browser.senate_efd_session.run_senate_efd_session` against the
live site, from this development sandbox's own network egress, with a
5-filing cap and fake storage callables (no real bronze writes):

```python
run_senate_efd_session(
    read_existing_sha256=lambda meta_key: None,
    write_bytes=lambda key, data: None,
    now=lambda: datetime.now(UTC).isoformat(),
    today=lambda: date(2026, 9, 25),
    rate_limiter=RateLimiter(min_interval=1.0),
    max_filings=5,
)
```

## Result

**2026-09-25, development sandbox network — BLOCKED at warm-up, before the
PTR search form was ever reached:**

```text
SenateEfdBlockedError(
    context="reaching the PTR search form after warm-up",
    outcome="blocked_akamai",
    status_code=403,
    final_url="https://efdsearch.senate.gov/search/home/",
)
```

The warm-up navigation to `SENATE_HOME_URL` itself came back `403 Access
Denied` (Akamai's own block-page shape), the same way a plain `curl` from
this same network does — this sandbox's egress IP is not one of the
environments #23 (local/dev network) or #29 (a real AWS Lambda egress IP)
confirmed clears the Akamai bot/fingerprint check. This is expected and not
a code defect: `#67`'s scope is the pure-mechanics layer, runnable and
demoable by hand, not a claim that every network this code happens to run
from clears the check.

**What this run does confirm**: the bounded-timeout guard added around the
PTR-search-form locators (`check(timeout=10_000)` /
`fill(timeout=10_000)`) works as intended — a warm-up that never reaches
the form fails fast (~10s) with a classified `SenateEfdBlockedError`
carrying `status_code`/`final_url` context, instead of hanging for each
field's full default Playwright timeout and then crashing with a raw,
uncontextualized `TimeoutError`. `classify_probe_result` correctly read the
home page's own 403 body as `blocked_akamai` (an `"Access Denied"` marker
present), the same classification `probes/senate_akamai_probe.py`'s own
attempts 1–4 hit before that probe was corrected (see
`docs/research/senate-akamai-lambda-probe.md`).

**Not yet re-verified from this session**: an end-to-end `"cleared"` run
(search form submitted, PTR entries parsed, filings fetched and written) —
that requires running from a network #23 or #29 already confirmed clears
the check (a local/dev network, or a real Lambda egress IP), which this
sandbox is neither. A future run from one of those environments should
confirm the full flow before this collector actually goes into a scheduled
Lambda (later ticket, per #67's explicit no-infra/no-Docker scope).

## Update (#68): the block was never about network origin

**The conclusion above is wrong**, discovered while chasing the identical
403 from `handlers/senate_collect_automated_handler.py`'s own RIE test
(`docs/research/senate-collect-automated-handler-rie-test.md`). The
Claude Code Playwright plugin's own browser (`mcp__plugin_playwright_*`),
run from this exact machine/network, loaded `SENATE_HOME_URL` cleanly —
`eFD: Home`, no 403 — on the same request this module's
`run_senate_efd_session` gets blocked on. Same network, same machine,
different outcome: the variable was never the egress IP.

Diffing the plugin browser's fingerprint (`navigator.webdriver`,
`navigator.userAgent`) against a throwaway Playwright script launched the
same way this module does isolated two candidate signals, tested against
the live site from this same network across all four combinations
(throwaway diagnostic script, not committed, same posture as every other
hand test here):

| `--disable-blink-features=AutomationControlled` | `webdriver` | User-Agent | Result |
|---|---|---|---|
| absent (original) | `true` | `...HeadlessChrome/153...` | `403`, Akamai marker |
| present | `false` | `...HeadlessChrome/153...` | `403`, Akamai marker |
| absent | `true` | `...Chrome/153...` (Headless stripped) | **`200`**, real `eFD: Home` page |
| present | `false` | `...Chrome/153...` (Headless stripped) | **`200`**, real `eFD: Home` page, `prohibition_agreement` checkbox present |

The full matrix isolates the actual variable: the User-Agent's
`HeadlessChrome` substring is what Akamai's check keys off — `200` in both
rows where it's stripped, `403` in both where it isn't, regardless of
`navigator.webdriver`. `--disable-blink-features=AutomationControlled` is
not shown to matter to this check either way; it stays in
`LAMBDA_SAFE_CHROMIUM_LAUNCH_ARGS` as a standard, low-cost headless-detection
precaution against a stricter future check, not because this one needs it.

Neither #23's "local/dev network" framing nor #29's "Lambda egress IP"
framing was the operative variable after all — both of those runs happened
to use a browser setup (Selenium with a system Chrome binary; a real
Lambda's own Playwright launch) whose UA string apparently didn't carry the
`HeadlessChrome` tell, not because their network origin was special.
`run_senate_efd_session`/`probes/senate_akamai_probe.run_probe` now pass
`de_headless_user_agent(browser)` to `browser.new_page()`; see
`docs/research/senate-collect-automated-handler-rie-test.md`'s own Update
section for the resulting real, `"written"` end-to-end run and its verified
MinIO bronze object.
