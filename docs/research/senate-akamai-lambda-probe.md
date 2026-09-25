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

**2026-09-25, preliminary — inconclusive, needs a rerun.** #29 itself scopes
this ticket as "stays open and unclaimed here until a future
implementation/cloud-lift effort picks it up"; the human operating this repo
went ahead and ran the probe anyway against a real AWS account
(`us-east-1`), working through a chain of deploy-time bugs along the way
(Playwright headless-shell binary vs. full Chromium, `PLAYWRIGHT_BROWSERS_PATH`
resolving under the wrong `$HOME` at Lambda runtime, missing
`--no-sandbox`/`--disable-gpu`/`--disable-dev-shm-usage`/`--single-process`
launch flags — see git history on `feat/senate-lambda-akamai-probe` for each
fix). Filing probed: `b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f`.

Raw result:

```json
{
  "filing_id": "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f",
  "status_code": 200,
  "outcome": "ambiguous",
  "html_excerpt": "<title>eFD: Home</title> ..."
}
```

`status_code` is 200 (not the classic Akamai 403 confirmed live in #17/#23),
but the page title is **`eFD: Home`**, not
`senate_collect.py`'s confirmed-live cleared marker
(`"eFD: Print Periodic Transaction Report"`) — the request did not land on
the filing itself. `classify_probe_result` correctly calls this
`"ambiguous"` rather than guessing: a 200 that isn't the filing page could
mean an Akamai soft-block shaped as a redirect to the homepage (a different
shape than the hard 403 block #17/#23 saw, but still a block), *or* some
other non-Akamai redirect/gate unrelated to bot detection. This run's
`ProbeResult` predates the `final_url` field (added right after, see
`senate_akamai_probe.py`), so there's no direct proof a redirect actually
happened rather than the URL itself just serving that content — that's
exactly the missing signal a rerun now captures.

**Not yet settled.** Next step: rerun with the current probe code (`git pull`,
`./scripts/deploy-senate-akamai-probe.sh up` to redeploy, then `invoke` again
against the same or a fresh filing id) and record here:

- `final_url` — confirms whether a redirect happened and to where.
- Outcome (`cleared` / `blocked_akamai` / `blocked_other` / `ambiguous`) and
  HTTP status code.
- If blocked: whether it looks like a hard block (consistent across retries,
  matches Akamai's known block-page shape) or something workaroundable
  (rate-limit-shaped, intermittent, or a different failure mode entirely).
- Date run and which AWS region/account the Lambda egress IP came from.

That result is what unblocks #28's design decision (manual-only vs.
headless-browser automation step) from "contingent, unverified" to settled.
