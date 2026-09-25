# Extract stage packaging (resolving ADR-0001's deferred item) and actual Lambda count

#43 implements the orchestration shape #18 settled: collect, extract,
ticker/LLM-fallback and silver-write chained via SQS, S3-key references
only, one filing per invocation, uniform DLQ with a slower backoff for
ticker/LLM-fallback. Two things needed a decision beyond that shape once
implementation started.

## Tesseract packaging for the extraction Lambda

ADR-0001 chose a container image so Tesseract could be installed with "a
plain `yum`/`apt` call" instead of a hand-built binary, but left *how*
unresolved (`docs/local-dev.md` flagged it as a follow-up). Checked directly
against both the AWS Lambda Python 3.12 base image and plain
`amazonlinux:2023`: neither's `dnf` repos carry a `tesseract` package at
all — not an EPEL gap, the package simply isn't published for AL2023. A
plain Debian image (`python:3.12-slim`) does carry `tesseract-ocr` via
`apt-get`, and is already what `.github/workflows/ci.yml` installs it from.

**Decision**: `docker/extract.Dockerfile` uses AWS's documented
"alternative base image" pattern — `python:3.12-slim`, Tesseract via
`apt-get install tesseract-ocr`, the Lambda Runtime Interface Client
(`awslambdaric`) installed via `pip`, and the Runtime Interface Emulator
(`aws-lambda-rie`) downloaded separately for local/RIE testing, since a
non-AWS base image bundles neither. Every other stage's image stays on the
AWS base image (`lambda.Dockerfile`, `house_collect.Dockerfile`,
`senate_collect.Dockerfile`), since none of them need Tesseract. Verified
locally: the image builds, and a real House PTR fixture round-trips through
it via the RIE into MinIO silver Parquet (see #43's PR for the transcript).

### Considered options

- **Static Tesseract binary on the AWS base image**: rejected in ADR-0001
  already, for the same maintenance-burden reason.
- **EPEL-equivalent repo on AL2023**: not applicable — the package isn't
  published there at all, so enabling a wider repo wouldn't have helped.
- **Alternative base image (Debian) + `awslambdaric`** (chosen): matches
  AWS's own documented pattern for exactly this situation, and is the
  plain-package-manager installation ADR-0001 always intended.

## Actual Lambda count: three, not four

#18's design named four Lambdas (collect, extract, ticker/LLM-fallback,
silver-write). By the time #43 started, #41 had already wired ticker
resolution and LLM fallback into `extract_handler.py` itself (see that
module's docstring), and no separate silver-write business logic exists
beyond the `put_object` calls already in the same handler — there's no pure
function boundary between "extract," "ticker/LLM-fallback" and
"silver-write" as actually implemented, so splitting them into separate
Lambdas now would add SQS hops and re-serialization with no behavior
attached to the seam.

**Decision**: keep the three-Lambda topology (`house-collect`,
`senate-collect` — not chained via SQS, see #18's S3-event-trigger
decision — and `extract`, which also performs ticker/LLM-fallback and
silver-write). `infra/modules/lambda-stage`'s `queue_visibility_timeout_seconds`
is set higher on `extract`'s queue than on `house-collect`'s, since
`extract`'s Lambda is the one actually doing ticker/LLM-fallback work; this
is what #43's "the ticker/LLM-fallback stage's DLQ" bullet resolves to
given the current code. Revisit as a fresh decision if ticker/LLM-fallback
or silver-write ever need independent scaling, retry posture, or
concurrency limits from extraction itself — nothing here forecloses
splitting them out later.

### Considered options

- **Split into four Lambdas now, to match #18 literally**: rejected — no
  behavior exists at the "ticker/LLM-fallback" or "silver-write" boundaries
  to justify a Lambda cold-start, an SQS hop, and re-fetching the bronze PDF
  a second time for a step that has no independent pure function today.
- **Three-Lambda topology, `extract`'s DLQ backoff carries the ticker/
  LLM-fallback posture** (chosen): matches the code as it actually stands.

## Consequences

`infra/modules/lambda-stage` (a Lambda + its own SQS queue/DLQ + reserved
concurrency, per ADR-0009) is implemented and `terraform validate`-clean,
but not yet wired into a root module: that needs the state-backend
bootstrap and an ECR repository per stage, neither provisioned yet (ADR-0009
describes them but `infra/` had no code at all before this PR). Wiring the
module into a deployable root stack, plus House's EventBridge schedule and
Senate's bronze-bucket S3 event notification, is tracked as follow-up
rather than done here.
