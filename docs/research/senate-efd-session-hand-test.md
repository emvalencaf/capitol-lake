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
