# Local development

How pipeline stages are laid out under `src/`, how the local S3 emulation
(MinIO) mirrors the AWS key layout, and how to run a stage the same way it
will run in Lambda.

## `src/` layout: pure function plus thin handler

```
src/capitol_lake/
├── keys.py              # shared S3 key-layout helpers (bronze_key, silver_key)
├── stages/
│   └── <stage>.py        # one pure function per pipeline stage
└── handlers/
    └── <stage>_handler.py  # thin Lambda adapter for that stage
```

Each pipeline stage (collect, extract, ticker/LLM-fallback, silver-write) is
split in two:

- **`stages/<stage>.py`** — a pure function. It takes an S3 key or raw bytes
  and returns a plain, structured dict. It never touches S3, SQS, or any
  other AWS service directly. This is what tests call, and the only thing
  tests call: no AWS mocking, no MinIO, no LocalStack needed for a
  stage-level unit test.
- **`handlers/<stage>_handler.py`** — a thin `handler(event, context)`
  Lambda entry point that unpacks the event, calls the pure function, and
  returns its result. Handlers stay thin by convention and are not
  unit-tested; `src/capitol_lake/handlers/stub_handler.py` and
  `src/capitol_lake/stages/stub.py` are the reference pair new stages copy.

## S3 key layout

Local (MinIO) and AWS (S3) use the identical key strings; only the endpoint
differs. Built by `src/capitol_lake/keys.py`:

- Bronze: `bronze/<chamber>/year=<year>/<doc_id>.<ext>`
- Silver: `silver/<table>/chamber=<chamber>/year=<year>/part-<doc_id>.parquet`

## Bronze contract: hash-gated idempotent writer

`src/capitol_lake/stages/bronze_write.py` is the chamber-agnostic bronze
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

`src/capitol_lake/stages/house_collect.py` is the first caller of the bronze
contract. `route_doc_id` classifies a House doc id as `"digital"` (`20…`
prefix) or `"scanned"` (`82…`/`91…` prefix) with no network call, and
`parse_house_index` parses the annual index ZIP's XML into routed entries,
also with no network call — both are unit-tested directly. `collect_house`
orchestrates the full run: fetch the index, then for each entry rate-limit
(`RateLimiter`, ~1 request/second by default) before fetching the filing and
running it through `bronze_write`. All network and S3 access is injected as
plain callables, so `collect_house` itself is tested against fakes with no
live network call and no MinIO; only `handlers/house_collect_handler.py`
wires it to real `urllib` fetches and a real `boto3` S3 client.

## Senate collector

`src/capitol_lake/stages/senate_collect.py` is the second caller of the
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
`route_filing_kind`/`parse_senate_index` route and filter that response's
rows — `[first, last, office, html_link, filed_date]`, confirmed against a
real recorded response (`tests/fixtures/senate_search_sample.json`) and a
real fetched `/ptr/` filing page (`tests/fixtures/senate_ptr_sample.html`,
round-tripped byte-for-byte through `bronze_write` in a test) — to
`/ptr/` (electronic, clean HTML) entries with no network call, deriving each
entry's year from its `filed_date` column since the response isn't scoped to
one year. `/paper/` (scanned-GIF, pre-electronic-mandate) and every other
report kind the search surfaces (`annual`, `extension-notice/regular`, ...)
are skipped and never fetched, out of scope per the map (#30). `collect_senate`
then rate-limits (`RateLimiter`, ~1 request/second by default) and fetches
each `/ptr/` filing's HTML by its Senate eFD UUID, running it through
`bronze_write` exactly as `collect_house` does; a filing's UUID and an
amendment's own, separate UUID are used as `doc_id` unchanged, so the
existing idempotency contract applies without modification. Network and
storage access are fully injected so `collect_senate` itself is tested
against fakes with no live network call and no MinIO; only
`handlers/senate_collect_handler.py` wires it to real `urllib` fetches and a
real `boto3` S3 client — which only succeeds where the Akamai check passes
(a plain `urllib` request does not; see above).

## Extract stage

`src/capitol_lake/stages/extract.py` is the third caller of the bronze
contract's counterpart on the silver side. `extract_house_filing` takes a
bronze PDF's bytes plus its `bronze_key`, parses `chamber`/`year`/`doc_id`
back out of that key, routes to `digital_extract.extract_digital` or
`scanned_extract.extract_scanned` via `house_collect.route_doc_id` (no
manual classification), and serializes the resulting `Filing` and
`Transaction` rows into two Hive-partitioned Parquet part files — one per
silver table (`filings`, `transactions`), one part per `doc_id`
(`silver_key`, ADR 0008). Every transaction row extracted is kept regardless
of `asset_type`, with `asset_type` and the original `asset_description`
always present; this stage only routes and serializes, it never filters a
row out. Like every other stage here, the pure function never touches S3 —
it returns each part file's key and bytes, and
`handlers/extract_handler.py` (real `boto3` client) reads the bronze PDF and
writes both silver part files. It also raises `DocIdMismatchError` rather
than write a row whose own `doc_id` disagrees with the bronze key it's
partitioned under (the digital extractor reads `doc_id` from the PDF's own
footer, independently of the bronze key).

No `docker/extract.Dockerfile` or compose service yet: unlike the House and
Senate collectors, `dnf install tesseract` isn't available on the AWS Lambda
Python 3.12 base image's default repos, so packaging Tesseract into a
container image for this stage needs a static binary or an EPEL-equivalent
setup (ADR 0001), which is deferred rather than solved here. Exercise
`extract_handler.py` directly (plain call, with real `boto3`/MinIO clients
injected) instead of through the Lambda RIE until that's resolved.

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
uv run python -c "from capitol_lake.stages.stub import process; print(process('x'))"
```

## Adding a new stage

1. Add `stages/<name>.py` with a pure function: structured input in,
   structured dict out. Write its tests in `tests/` against that function
   only.
2. Add `handlers/<name>_handler.py`: unpack the Lambda event, call the pure
   function, return its result. No test needed.
3. Add a `docker-compose.yml` service for it, copied from `stub-stage`,
   pointing `dockerfile` at a `docker/<name>.Dockerfile` (copy
   `docker/lambda.Dockerfile`, adding a `pip install` layer if the stage has
   dependencies the stub doesn't).
