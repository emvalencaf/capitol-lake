# Senate eFD Akamai check: Lambda-origin probe (#29)

## Question

#23 confirmed, from a **local/dev network**, that a headless-Chromium
request (Selenium) clears the Senate eFD `/ptr/` Akamai bot/fingerprint
check that blocks a plain scripted `requests`/`urllib` call. #28's Senate
collector automation design (a headless-browser Playwright step inside the
cloud pipeline) is contingent on the same holding true from an actual **AWS
Lambda egress IP** — cloud IP reputation is a distinct, unverified variable
per #17's original note.

## Method

`infra/probes/senate-akamai-probe/` stands up a single, standalone Lambda
(not part of the main pipeline stack) running
`capitol_lake.probes.senate_akamai_probe.run_probe`: a real headless-Chromium
request via Playwright against one known `/ptr/` filing's print-view URL
(`SENATE_FILING_URL_TEMPLATE` in `stages/senate_collect.py`), classified by
`classify_probe_result` into `"cleared"`, `"blocked_akamai"`,
`"blocked_other"`, or `"ambiguous"` from the response's status code and body
— see that module's docstring for the exact markers.

Run once by hand per `infra/probes/senate-akamai-probe/README.md`, then torn
down; this is a throwaway diagnostic, not infra kept running.

## Result

**Superseded once, see below — two cold-request runs on 2026-09-25 turned
out not to be meaningful evidence, and `run_probe` was corrected as a
result.** #29 itself scopes this ticket as "stays open and unclaimed here
until a future implementation/cloud-lift effort picks it up"; the human
operating this repo went ahead and ran the probe anyway against a real AWS
account (`us-east-1`), working through a chain of deploy-time bugs along the
way (Playwright headless-shell binary vs. full Chromium,
`PLAYWRIGHT_BROWSERS_PATH` resolving under the wrong `$HOME` at Lambda
runtime, missing `--no-sandbox`/`--disable-gpu`/`--disable-dev-shm-usage`/
`--single-process` launch flags — see git history on
`feat/senate-lambda-akamai-probe` for each fix). Filing probed:
`b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f`.

Both attempts (the first without `final_url`, the second with it) landed on
`final_url` `https://efdsearch.senate.gov/search/home/` instead of the
filing:

```json
{
  "filing_id": "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f",
  "status_code": 200,
  "outcome": "ambiguous",
  "final_url": "https://efdsearch.senate.gov/search/home/",
  "html_excerpt": "<title>eFD: Home</title> ..."
}
```

**This was initially (wrongly) read as likely evidence of a Lambda-specific
bot/fingerprint soft-block.** Re-reading #23's own resolution comment
corrected that: #23's *successful* local probe also first landed on
`https://efdsearch.senate.gov/search/home/`, titled `eFD: Home` — the exact
same URL and title this Lambda probe got. #23's script then went on to use
that same browser session for further navigation; #35's second comment
similarly describes fetching real filings via "that Selenium-established
session," not a single cold request straight at a filing URL. Every real,
confirmed-successful local run this repo has on record involved navigating
the site first, in the same browser context, before ever requesting a
filing — this probe's first two runs never did that; they hit the filing URL
cold, in a fresh browser page with no prior navigation. Landing on
`/search/home/` may simply be this site's ordinary behavior for *any*
browser (local or Lambda) that hasn't loaded anything yet, not a
Lambda-specific block at all. **These two runs are retracted as evidence
either way** — not because the observation was wrong, but because the
comparison (cold Lambda request vs. warmed-up local session) wasn't
apples-to-apples.

### Attempt 3: warmed-up session, `home_status_code` added

`run_probe` was corrected to navigate to `SENATE_HOME_URL` first, in the
same page, before requesting the filing. Result: `home_status_code: 200`
(the homepage itself loads fine, not blocked), but the filing request still
landed back on `final_url` `.../search/home/`, `outcome: "ambiguous"` —
same shape as before. Still not apples-to-apples with the local runs: #23's
successful probe *and* #35's real collection run both went through the
site's own `prohibition_agreement` checkbox gate (a Django session
requirement, independent of Akamai) before fetching anything — a bare visit
to the homepage isn't the same as accepting that agreement.

### Attempt 4: agreement accepted, still redirected — genuinely ambiguous

`run_probe` was corrected again to find the `prohibition_agreement`
checkbox, check it, and submit its form via JS (a plain Playwright
`Locator.check()` hung for the full 30s timeout on the real deploy —
see git history for that fix) before requesting the filing. Result:

```json
{
  "filing_id": "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f",
  "status_code": 200,
  "outcome": "ambiguous",
  "final_url": "https://efdsearch.senate.gov/search/home/",
  "home_status_code": 200,
  "agreement_accepted": true
}
```

`agreement_accepted: true` only confirms the checkbox was found and the JS
submit call didn't throw — it does **not** confirm the site actually
accepted the agreement server-side. This result can't yet distinguish two
different failures:

1. The agreement submission itself was rejected/ignored (landed back on
   `SENATE_HOME_URL` immediately, before the filing was ever requested) —
   would point at something wrong with the submission (stale CSRF token,
   Akamai intervening on that specific POST, a markup assumption that's
   wrong).
2. The agreement succeeded (landed on `/search/`) but the *filing* request
   afterward lost that session and bounced back on its own — would point at
   a session/cookie-persistence issue specific to the filing request, a
   genuinely new and more interesting finding.

`run_probe` was corrected to also capture `post_agreement_url`. Result:

```json
{
  "post_agreement_url": "https://efdsearch.senate.gov/search/home/",
  "final_url": "https://efdsearch.senate.gov/search/home/",
  "outcome": "ambiguous",
  "agreement_accepted": true
}
```

**Case 1 confirmed: the agreement submission itself was rejected/ignored** —
`post_agreement_url` equals `SENATE_HOME_URL`, i.e. the JS-driven
`checked=true; form.submit()` bounced straight back to the same page,
before the filing was ever requested.

### Attempt 5: confound identified — the submission method itself, not (necessarily) Lambda

The JS-only submit fires a *synthetic* DOM event
(`event.isTrusted: false`) rather than a real user gesture — a signal some
bot defenses specifically check for, independent of IP origin. This is a
real confound: attempt 4's rejection could reflect a Lambda-specific block,
or it could just as easily reflect "this exact synthetic-submit approach
would fail from a local network too." Re-reading the original
`Locator.check()` timeout's own log (attempt 2's fix) supports the latter:
the log showed the click and its resulting navigation both completing
("click action done", "navigations have finished") — `check()`'s 30s hang
came *after* that, re-verifying the checkbox is still in the checked state,
which can never succeed once its own `onchange` handler has already
navigated the page away (the original element is detached). That strongly
suggests the real click's own submission likely succeeded before attempt
2 was ever recorded as a hard failure — we just never read the result.

`run_probe` now uses a real, trusted `Locator.click()` (not `.check()`, so
no unreachable post-click "still checked" verification; timeout tolerated
via `try`/`except`, since the click and its navigation may already have
succeeded by the time it fires) instead of the JS-only submit. **Not yet
rerun with this fix.** Next step: redeploy
(`./scripts/deploy-senate-akamai-probe.sh up`) and `invoke` again, and
record here:

- `post_agreement_url` — accepted (`/search/`) or still rejected (bounced
  back to `SENATE_HOME_URL`) with a *real* click this time?
- `final_url` and `outcome` for the filing request that follows.
- If still redirected/blocked even with a real click: this would be much
  stronger evidence of an actual Lambda-origin block (the synthetic-event
  confound above would be ruled out), and whether it looks like a hard
  block (consistent across retries, matches Akamai's known block-page
  shape) or something workaroundable (rate-limit-shaped, intermittent, or a
  different failure mode entirely).
- Date run and which AWS region/account the Lambda egress IP came from.

That result is what unblocks #28's design decision (manual-only vs.
headless-browser automation step) from "contingent, unverified" to settled.
