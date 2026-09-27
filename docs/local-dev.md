# Local development

How pipeline stages are laid out under `src/`, how the local S3 emulation
(MinIO) mirrors the AWS key layout, and how to run a stage the same way it
will run in Lambda.

## `src/` layout: shared package plus pure function plus thin handler

Per ADR 0014, `src/shared/` holds code used by more than one Lambda image;
each Lambda gets its own top-level package containing only its own stage
logic and handler:

```
src/shared/
├── keys.py              # shared S3 key-layout helpers (bronze_key, silver_key)
└── ...                   # other cross-Lambda code (schema, orchestration, ...)
src/<lambda-name>/
├── <stage>.py            # one pure function for that Lambda's stage
└── handler.py            # thin Lambda adapter for that stage
```

Each pipeline stage (collect, extract, ticker/LLM-fallback, silver-write) is
split in two:

- **`<lambda-name>/<stage>.py`** — a pure function. It takes an S3 key or
  raw bytes and returns a plain, structured dict. It never touches S3, SQS,
  or any other AWS service directly. This is what tests call, and the only
  thing tests call: no AWS mocking, no MinIO, no LocalStack needed for a
  stage-level unit test.
- **`<lambda-name>/handler.py`** — a thin `handler(event, context)` Lambda
  entry point that unpacks the event, calls the pure function, and returns
  its result. Handlers stay thin by convention and are not unit-tested;
  `src/stub/handler.py` and `src/stub/process.py` are the reference pair
  new stages copy.

A Lambda's Docker image `COPY`s `src/shared/` plus its own package only —
never another Lambda's package (ADR 0014).

## S3 key layout

Local (MinIO) and AWS (S3) use the identical key strings; only the endpoint
differs. Built by `src/shared/keys.py`:

- Bronze: `bronze/<chamber>/year=<year>/<doc_id>.<ext>`
- Silver: `silver/<table>/chamber=<chamber>/year=<year>/part-<doc_id>.parquet`

## Bronze contract: hash-gated idempotent writer

`src/shared/bronze_write.py` is the chamber-agnostic bronze
contract shared by every collector. Given candidate bytes for a `doc_id` and
the sha256 already on record for it (or `None` if it has never been
stored), `bronze_write` decides — without touching S3 or the network — one
of two outcomes:

- **No-op**: the candidate's hash matches `existing_sha256`. Nothing is
  written.
- **Write**: first write, or the candidate's hash differs. First write uses
  the original `bronze_key`; a differing hash instead produces a new
  versioned key, `<doc_id>.<sha256[:8]>.<ext>`, and the original key is
  never overwritten. Every write carries a sidecar `.meta.json` (`bronze_meta_key`)
  with `source_url`, `fetched_at`, `sha256`, `chamber`, `doc_id`, `year`,
  `ext`, `index_row`.

The caller (a future collector stage) is responsible for reading the prior
sha256 from the existing sidecar and performing the actual S3 write per the
returned plan.

## House collector

`src/house_collect/collect.py` is the first caller of the bronze contract.
`shared.doc_id.route_doc_id` classifies a House doc id as `"digital"` (`20…`
prefix) or `"scanned"` (`82…`/`91…` prefix) with no network call — shared
with `extract_data`, which routes bronze keys the same way — and
`parse_house_index` parses the annual index ZIP's XML into routed entries,
also with no network call — both are unit-tested directly. `collect_house`
orchestrates the full run: fetch the index, then for each entry check
whether its `doc_id` already has a stored sha256 — if so, it's `skip`ped
with **no fetch at all**, since a House Clerk correction is filed under a
brand-new `DocID` rather than silently replacing an existing one's content
(high-confidence primary-source finding, not an absolute guarantee — see
`docs/research/house-ptr-amendment-doc-id-behavior.md`). Only a never-seen
`doc_id` is rate-limited (`RateLimiter`, ~1 request/second by default),
fetched, and run through `bronze_write` (which will always plan a `"write"`
for it, having nothing to hash-compare against). All network and S3 access
is injected as plain callables, so `collect_house` itself is tested against
fakes with no live network call and no MinIO; only `house_collect/handler.py`
wires it to real `urllib` fetches and a real `boto3` S3 client.

## Senate collector

`src/senate_collect/collect.py` is the second caller of the
bronze contract, writing `bronze/senate/year=<year>/<filing_id>.html`. Unlike
House, it is not scheduled: the Senate eFD search UI is Akamai
bot/fingerprint-protected (#17, #23) — confirmed live (2026-09-23) even on
individual `/ptr/` filing pages, and even reusing an authenticated session's
cookies with a plain HTTP client (`requests`); only an actual browser engine
(headless Chromium via Selenium) clears the check. Per #18 the stage stays
manual — a human (or a local headless-browser step, per #23's method) runs
the eFD search, captures the JSON body its own DataTables endpoint
(`POST /search/report/data/`) returns, and calls `collect_senate(response,
...)` (or invokes `senate_collect_handler` with `event["response"]` set to
that capture) directly, rather than this stage discovering the index itself.
`shared.senate_index`'s `route_filing_kind`/`parse_senate_index` route and filter that response's
rows — `[first, last, office, html_link, filed_date]`, confirmed against a
real recorded response (`tests/fixtures/senate_search_sample.json`) and a
real fetched `/ptr/` filing page (`tests/fixtures/senate_ptr_sample.html`,
round-tripped byte-for-byte through `bronze_write` in a test) — to
`/ptr/` (electronic, clean HTML) entries with no network call, deriving each
entry's year from its `filed_date` column since the response isn't scoped to
one year. `/paper/` (scanned-GIF, pre-electronic-mandate) and every other
report kind the search surfaces (`annual`, `extension-notice/regular`, ...)
are skipped and never fetched, out of scope per the map (#30). `collect_senate`
calls `known_doc_ids()` once to get every filing UUID already on record,
then for each entry checks membership *before* touching the network: a
known UUID (a filing's UUID, or an amendment's own, separate UUID) is
skipped with no fetch and no rate-limit charged, exactly like
`collect_house` does for a known House `doc_id` — same ADR-0018 policy, but
unlike House, not backed by primary-source research confirming Senate
amendments really do get a separate UUID (see `collect_senate`'s docstring
for the caveat). Only a never-seen UUID is rate-limited (`RateLimiter`, ~1
request/second by default), fetched by its Senate eFD UUID, and run through
`bronze_write` exactly as `collect_house` does. Network and storage access
are fully injected so `collect_senate` itself is tested against fakes with
no live network call and no MinIO; only `senate_collect/handler.py` wires it
to real `urllib` fetches and a real `boto3` S3 client — which only succeeds
where the Akamai check passes (a plain `urllib` request does not; see
above).

`src/senate_collect_automated/browser_session.py` (#67) is the automated
alternative #28 resolved on: `run_senate_efd_session` drives one
authenticated Playwright session through the entire flow itself — warm-up,
agreement gate, PTR search form for a 7-day lookback window, then reuses
`shared.senate_index`'s `parse_senate_index`/`bronze_write`/`RateLimiter`
exactly as above, skipping a known filing UUID with **no page navigation at
all** (same `known_doc_ids()`-first policy as `collect_senate`, ADR-0018) —
instead of a human capturing the DataTables response by hand first. It
classifies every response it depends on (reaching the search form, the
search response itself, each filing fetch it actually makes) via
`shared.senate_efd_classification.classify_probe_result`/its own
`classify_search_response` (the former moved permanently from
`senate_akamai_probe/probe.py`, #29's throwaway probe) and raises
immediately on anything but `"cleared"`. Clearing the check turned out to
depend on a browser fingerprint signal, not network origin at all (#68, see
`docs/research/senate-efd-session-hand-test.md`'s Update section):
`run_senate_efd_session` passes `de_headless_user_agent(browser)` to
`browser.new_page()`, stripping the default headless Chromium UA's
`HeadlessChrome` substring — a real Lambda egress IP is not required.

`senate_collect_automated/handler.py` (#68) is the thin Lambda adapter for
that flow: unlike `senate_collect/handler.py`, it takes no
`event["response"]` capture — the browser session drives the search itself —
so `event` is unused, and it wires `run_senate_efd_session` to a real
`boto3` S3 client the same way every other handler does. It enqueues its own
`extract_queue_message` per bronze key it wrote this run, exactly like
`senate_collect/handler.py` and `house_collect/handler.py` (ADR-0016).

`docker/senate_collect_automated.Dockerfile` packages it the way the
now-retired `senate_akamai_probe` Lambda's Dockerfile did (#29, #70) rather
than the plain `docker/lambda.Dockerfile` base every stdlib-only stage uses: Playwright's
Chromium needs real shared libraries the AWS Lambda base image's minimal
userland doesn't carry, so it follows the same alternative-base-image
pattern as `docker/extract.Dockerfile` (ADR-0011) — `awslambdaric` and a
separately-downloaded `aws-lambda-rie` for local testing, `playwright
install --with-deps chromium`, and `PLAYWRIGHT_BROWSERS_PATH` pinned so the
non-root Lambda runtime user finds the browser the root build user
installed. Build and run it the same way as every other stage:

```bash
docker-compose up -d --build senate-collect-automated-stage
curl -XPOST "http://localhost:9104/2015-03-31/functions/function/invocations" \
  -d '{}'
```

A run only succeeds where the Akamai check clears (see above) — a blocked
run raises `SenateEfdBlockedError`, which the RIE endpoint reports as an
invocation error rather than a bronze write. With both fingerprint fixes in
place, a run from this development sandbox's own network wrote a real
bronze object and its `.meta.json` sidecar, verified directly in MinIO; see
`docs/research/senate-collect-automated-handler-rie-test.md` for the full
result.

## Orchestration: SQS chain and stage-to-stage handoff (#43)

Per the shape #18 settled and ADR-0016 finished generalizing, stages are
chained via SQS carrying only S3-key references (never document bytes):
every collector (`house_collect`, `senate_collect`, `senate_collect_automated`)
builds its own `extract_queue_message` and sends it to extract's queue for
each bronze key it wrote. `shared/orchestration.py`'s
`bronze_key_records_from_event` is the one place a handler unpacks its
event, dispatching on shape — a plain `{"bronze_key": ...}` invocation
(manual/RIE testing, every handler still accepts this), an SQS event (each
record's `body` is `extract_queue_message`'s JSON, `{"bronze_key": ...}`),
or a direct S3 event (each record's own `s3.object.key`, kept for any
future stage still invoked that way, though nothing produces one today).
Every bronze key extracted off an SQS record carries that record's
`messageId`, giving it a retry/DLQ handle, while a plain or direct-S3 record
gets `None`, so a handler can report a per-message failure without
re-deriving which records came off SQS itself, even in a batch that mixes
sources.
`keys.py`'s `parse_bronze_key` reverses `bronze_key()` back into
`chamber`/`year`/`doc_id`, shared by every stage that only receives a
bronze key.

`house_collect/handler.py` enqueues one SQS message per bronze key
`collect_house` actually wrote this run (never a `skipped` key) to
`EXTRACT_QUEUE_URL`, left unset by default so the handler still runs
standalone with no queue configured. `extract_data/handler.py` accepts a
batch of SQS records (batch size 1 in production, per #43) and reports a
per-message failure via `batchItemFailures` (`ReportBatchItemFailures`)
rather than letting one filing's exception fail the whole batch, using each
`BronzeKeyRecord.message_id` rather than every other record's raw shape; a
plain or direct-S3-event invocation still lets an exception raise, matching
every other handler.

Locally, ElasticMQ (`docker-compose.yml`'s `elasticmq` service, port 9324)
emulates SQS — chosen over LocalStack since LocalStack's SQS coverage is
Hobby-plan/non-commercial-only (`docs/research/free-tool-inventory.md`,
#4), and ElasticMQ is a free, Apache-2.0, SQS-only complement to MinIO's S3
emulation. `docker/elasticmq.conf` pre-creates the `extract-queue` queue on
boot, matching MinIO's `minio-init` bucket-creation pattern. Bring both up
alongside MinIO:

```bash
docker-compose up -d minio minio-init elasticmq
```

`infra/modules/lambda-stage` (Terraform, not yet wired into a root module —
see ADR 0011) is the reserved-concurrency/DLQ-per-stage configuration #43's
acceptance criteria calls for: one queue, one DLQ (14-day retention), and
`reserved_concurrent_executions` (default 5) per stage; a stage's
`queue_visibility_timeout_seconds` doubles as its retry backoff, set higher
on `extract`'s instance than the default per ADR 0011 (its Lambda also
performs ticker resolution and LLM fallback, so it gets the slower-backoff
DLQ posture #43 asks for on that stage, not more retries).

## Extract stage

`src/extract_data/extract.py` is the third caller of the bronze
contract's counterpart on the silver side. `extract_house_filing` takes a
bronze PDF's bytes plus its `bronze_key`, parses `chamber`/`year`/`doc_id`
back out of that key (`shared.keys.parse_bronze_key`), routes to
`digital_extract.extract_digital` or `scanned_extract.extract_scanned` via
`shared.doc_id.route_doc_id` (no manual classification), and serializes the
resulting `Filing` and `Transaction` rows into two Hive-partitioned Parquet
part files — one per silver table (`filings`, `transactions`), one part per
`doc_id` (`silver_key`, ADR 0008). Every transaction row extracted is kept
regardless of `asset_type`, with `asset_type` and the original
`asset_description` always present; this stage only routes and serializes,
it never filters a row out. Like every other stage here, the pure function
never touches S3 — it returns each part file's key and bytes, and
`extract_data/handler.py` (real `boto3` client) reads the bronze PDF and
writes both silver part files. It also raises `DocIdMismatchError` rather
than write a row whose own `doc_id` disagrees with the bronze key it's
partitioned under (the digital extractor reads `doc_id` from the PDF's own
footer, independently of the bronze key).

`docker/extract.Dockerfile` (ADR 0011) packages this stage: unlike every
other stage's image, it builds from a plain Debian base
(`python:3.12-slim`) rather than the AWS Lambda base image, since neither
that image's nor plain `amazonlinux:2023`'s `dnf` repos carry a `tesseract`
package at all. Tesseract installs the way ADR-0001 always intended — a
plain `apt-get install tesseract-ocr`, the same package
`.github/workflows/ci.yml` already installs — following AWS's documented
"alternative base image" pattern: `awslambdaric` (the Lambda Runtime
Interface Client) via `pip`, and `aws-lambda-rie` (the Runtime Interface
Emulator, bundled automatically on AWS's own base images but not on a
non-AWS one) downloaded separately, wired up by
`docker/extract-entrypoint.sh`. Build and run it the same way as every
other stage:

```bash
docker-compose up -d --build extract-stage
curl -XPOST "http://localhost:9103/2015-03-31/functions/function/invocations" \
  -d '{"bronze_key": "bronze/house/year=2024/20012345.pdf"}'
```

## Running MinIO locally

```bash
cp .env.example .env   # first time only
docker-compose up -d minio minio-init
```

This starts MinIO on `http://localhost:9000` (console on `:9001`) and
creates the `bronze` and `silver` buckets. Credentials come from `.env`
(`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`, default `minioadmin`/`minioadmin`
for local use only).

A stage that talks to S3 points its client at `AWS_ENDPOINT_URL_S3` (set to
`http://minio:9000` from inside docker-compose, `http://localhost:9000` from
the host) with the same credentials; nothing else changes when it later
points at real S3.

## Running a stage as a Lambda locally

Every stage's container image is built from `docker/lambda.Dockerfile` on
top of an AWS Lambda base image (per
[ADR-0001](adr/0001-lambda-container-image-packaging.md)). AWS's base images
already bundle the Lambda Runtime Interface Emulator (RIE) and use it
automatically whenever the container isn't actually running inside Lambda,
so no separate RIE install or wrapper script is needed.

```bash
docker-compose up -d --build stub-stage
curl -XPOST "http://localhost:9100/2015-03-31/functions/function/invocations" \
  -d '{"bronze_key": "bronze/house/year=2024/20012345.pdf"}'
# {"bronze_key": "bronze/house/year=2024/20012345.pdf", "ok": true}
```

The same pure function also runs as a plain call, with no container and no
MinIO:

```bash
uv run python -c "from stub.process import process; print(process('x'))"
```

## Adding a new stage

1. Add `src/<name>/<name>.py` with a pure function: structured input in,
   structured dict out. Write its tests in `tests/units/<name>/` against
   that function only.
2. Add `src/<name>/handler.py`: unpack the Lambda event, call the pure
   function, return its result. No test needed.
3. Add a `docker-compose.yml` service for it, copied from `stub-stage`,
   pointing `dockerfile` at a `docker/<name>.Dockerfile` (copy
   `docker/lambda.Dockerfile`, adding a `pip install` layer if the stage has
   dependencies the stub doesn't).
