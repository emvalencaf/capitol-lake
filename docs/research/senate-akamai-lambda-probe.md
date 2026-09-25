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

`run_probe` (see `senate_akamai_probe.py`) now navigates to
`SENATE_HOME_URL` first, in the same page, before requesting the filing —
replicating what the local runs actually did — and records that warm-up
navigation's own status as `home_status_code`. **Not yet rerun with this
fix.** Next step: redeploy (`./scripts/deploy-senate-akamai-probe.sh up`)
and `invoke` again, and record here:

- `home_status_code` and whether `SENATE_HOME_URL` itself renders normally
  (ToS-agreement text, per #23's description) or is blocked outright — a
  block there would be the harder, more decisive finding.
- `final_url` and `outcome` for the filing request that follows, now that
  the browser has a warmed-up session.
- If still redirected/blocked after the warm-up: whether it looks like a
  hard block (consistent across retries, matches Akamai's known block-page
  shape) or something workaroundable (rate-limit-shaped, intermittent, or a
  different failure mode entirely).
- Date run and which AWS region/account the Lambda egress IP came from.

That result is what unblocks #28's design decision (manual-only vs.
headless-browser automation step) from "contingent, unverified" to settled.
