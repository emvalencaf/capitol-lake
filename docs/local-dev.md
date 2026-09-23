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
