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

**2026-09-25, `us-east-1` — FAIL: the Lambda-origin request does not clear
the check the way #23's local-network probe did.** #29 itself scopes this
ticket as "stays open and unclaimed here until a future
implementation/cloud-lift effort picks it up"; the human operating this repo
went ahead and ran the probe anyway against a real AWS account, working
through a chain of deploy-time bugs along the way (Playwright headless-shell
binary vs. full Chromium, `PLAYWRIGHT_BROWSERS_PATH` resolving under the
wrong `$HOME` at Lambda runtime, missing
`--no-sandbox`/`--disable-gpu`/`--disable-dev-shm-usage`/`--single-process`
launch flags — see git history on `feat/senate-lambda-akamai-probe` for each
fix). Filing probed: `b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f`, requested URL
`https://efdsearch.senate.gov/search/view/ptr/b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f/`.

First attempt (predates `final_url`, `status_code` 200, `outcome`
`"ambiguous"`, page titled `eFD: Home`) was genuinely inconclusive: a 200
that isn't the filing page doesn't by itself prove a redirect happened.
Rerun with `final_url` added settled it:

```json
{
  "filing_id": "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f",
  "status_code": 200,
  "outcome": "ambiguous",
  "final_url": "https://efdsearch.senate.gov/search/home/",
  "html_excerpt": "<title>eFD: Home</title> ..."
}
```

`final_url` (`.../search/home/`) differs from the requested filing URL —
**a redirect happened**. This is the decisive fact: `senate_collect.py`'s own
confirmed-live comment (from #23) says a *cleared* request to this exact
print-view URL pattern needs no session/agreement cookie and returns the
filing's HTML directly, no redirect. #23's local-network probe got the
filing; this Lambda-origin probe got bounced to the site's homepage instead.

**Interpretation** (`classify_probe_result` still correctly reports
`"ambiguous"` — it only reads `status_code`/`html`, not `final_url`; this
call is a human judgment, per #29's own ask): most likely a **bot/fingerprint
soft-block**, not a session/agreement gate. Redirect-to-a-garden-page
(rather than an explicit 403 "Access Denied") is a standard Akamai Bot
Manager mitigation action, and #17's original note specifically flagged
"cloud IP may hit the same Akamai 403" as the open risk this ticket exists
to test — a redirect is a different *shape* of the same category of
response, not evidence against it. Residual uncertainty: this wasn't
re-verified against a fresh, contemporaneous local-network control (i.e.
confirming #23's exact result still holds *today*, not just in #23's own
run), so a site-side behavior change independent of Lambda vs. local-network
can't be fully ruled out.

**Hard block or workaroundable?** Unknown from a single run — this result
answers "does it clear the same way" (no), not "is it beatable with more
effort." Worth trying before writing off Playwright-in-Lambda entirely:
driving the full agreement flow (visit `/search/home/`, accept the terms,
carry the resulting session cookie into the filing request) the way a real
browser user would, since #23's "no cookie required" finding was itself
conditional on already clearing Akamai — an unclearing Lambda IP might
behave differently with a real session versus none. Until tried, treat this
as inconclusive-toward-hard-block, not confirmed-hard-block.

**Feeds into #28**: as of this result, a headless-browser collection step
inside the cloud pipeline is **not validated as viable** — #18's original
manual-only posture stands unless/until either the cookie-flow workaround
above is tried and clears, or the block is otherwise shown to be
inconsistent/workaroundable rather than a hard per-IP-range block.
