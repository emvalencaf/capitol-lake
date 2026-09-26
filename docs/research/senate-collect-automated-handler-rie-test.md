# Automated Senate collector handler: local RIE test (#68)

## What was run

`docker/senate_collect_automated.Dockerfile` built and run via
`docker-compose up -d --build senate-collect-automated-stage`, invoked
through the Runtime Interface Emulator against a real local MinIO (bronze
bucket created, `BRONZE_BUCKET=bronze`), exactly as `docs/local-dev.md`
documents for every other stage:

```bash
docker-compose up -d minio minio-init
docker-compose up -d --build senate-collect-automated-stage
curl -XPOST "http://localhost:9104/2015-03-31/functions/function/invocations" -d '{}'
```

## Result

**2026-09-26, this development sandbox's network egress — blocked at
warm-up**, the same outcome and for the same reason as
`docs/research/senate-efd-session-hand-test.md`'s #67 hand test:

```json
{"errorMessage": "Senate eFD session blocked while reaching the PTR search
form after warm-up: outcome='blocked_akamai', status_code=403,
final_url='https://efdsearch.senate.gov/search/home/'", "errorType":
"SenateEfdBlockedError"}
```

This sandbox's egress IP is not one of the networks #23/#29 confirmed
clears the Akamai check, so no real bronze write happened this run — that
requires invoking from a network already confirmed to clear it (a local/dev
network, or a real Lambda egress IP), same caveat as #67's own hand test.

**What this run does confirm** (#68's actual scope — the container and
handler plumbing, not the live Akamai outcome, which #67 already owns):

- `docker/senate_collect_automated.Dockerfile` builds cleanly and its
  Playwright/Chromium install is visible at runtime to the Lambda runtime's
  non-root sandbox user (the exact `PLAYWRIGHT_BROWSERS_PATH` fix
  `docker/senate_akamai_probe.Dockerfile` proved out) — the browser actually
  launches and navigates inside the RIE container; a `PLAYWRIGHT_BROWSERS_PATH`
  regression would instead surface as a browser-executable-not-found error,
  not a classified `SenateEfdBlockedError`.
- `handlers/senate_collect_automated_handler.py` correctly wires a real
  `boto3` S3 client (pointed at MinIO via `AWS_ENDPOINT_URL_S3`) into
  `run_senate_efd_session`, and the RIE endpoint reports the raised
  `SenateEfdBlockedError` as a structured invocation error rather than
  crashing the container.
- The image's own `aws-lambda-rie` download needed its version tag
  corrected to the `v`-prefixed form GitHub actually publishes
  (`RIE_VERSION=v1.37`, not the unprefixed `1.20` default carried over from
  `docker/senate_akamai_probe.Dockerfile`, which 404s and left `rapid`
  unable to start) — fixed in this Dockerfile only; the probe's own
  Dockerfile is untouched (#29, already run and torn down).

A future run from a network #23/#29 already confirmed clears the check
should show a real `"written"`/`"noop"` result and real bronze objects in
MinIO, the same way #67's own follow-up note describes.
