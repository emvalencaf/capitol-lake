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

**Not yet run.** This ticket (#29) is explicitly out of this map's
implementation scope ("stays open and unclaimed here until a future
implementation/cloud-lift effort picks it up") — only the probe's code and
standalone infra were built here, per that scoping. A future session running
`infra/probes/senate-akamai-probe/` should record here:

- Outcome (`cleared` / `blocked_akamai` / `blocked_other` / `ambiguous`) and
  HTTP status code.
- If blocked: whether it looks like a hard block (consistent across retries,
  matches Akamai's known block-page shape) or something workaroundable
  (rate-limit-shaped, intermittent, or a different failure mode entirely).
- Date run and which AWS region/account the Lambda egress IP came from.

That result is what unblocks #28's design decision (manual-only vs.
headless-browser automation step) from "contingent, unverified" to settled.
