# Architecture

This page explains how a member of Congress's stock-trading disclosure
travels from a public government website into Capitol Lake's queryable
Silver tables. It starts with a plain-language walkthrough for a reader who
doesn't work on this codebase day to day, then goes stage by stage for a
contributor who does. Terms in this doc follow [CONTEXT.md](../CONTEXT.md)'s
vocabulary (Filing, Transaction, Bronze, Silver, etc.) — that file is the
place to look up a term that's unfamiliar here.

## The short version

Every day, the pipeline checks the House and Senate financial-disclosure
sites for new stock-trading reports (PTRs). It downloads whatever's new and
saves it untouched, exactly as published — that's the **Bronze** layer, a
permanent, unedited archive. It then reads each document, pulls out the
individual trades it describes, fills in a few details that aren't printed
on the page (like a missing ticker symbol), and writes the result into a
structured, queryable table — that's the **Silver** layer, the version an
analyst or a dashboard actually queries. House collection is fully
automated; Senate collection is automated with a manual fallback, because
the Senate's disclosure site actively blocks automated traffic from cloud
IP ranges (see [ADR 0013](adr/0013-senate-html-extraction-design.md) for
the extraction side of that story). Everything runs on AWS Lambda,
triggered on a schedule, with S3 as the only durable storage.

The rest of this page is the same story at implementation depth, plus the
two diagrams referenced from the acceptance criteria.

## Pipeline stages

### 1. Collect (Bronze)

**House.** A scheduled Lambda, triggered daily by EventBridge, lists that
year's House PTR filings and downloads any Filing not already in Bronze
(`house_collect.py`). Each Filing is written to S3 byte-for-byte — Bronze
never edits or re-encodes what it collects. A successful write enqueues the
new bronze key onto the extract stage's SQS queue.

**Senate.** The Senate's eFD search UI is protected against bot and
fingerprint-based traffic, and a sandboxed request from a cloud egress IP
hits the same block a script would — so the Senate collector runs two ways:
an automated Lambda that drives the search through a real headless browser
session, and a manual fallback (a human runs the same flow locally and
uploads the result) for whenever the automated path doesn't clear the
block. Both paths write to the same Bronze bucket; there is no EventBridge
schedule for Senate, but each path's own handler enqueues the new bronze
key onto extract's SQS queue itself, exactly like House.

Every Lambda in the pipeline, House and Senate collectors included, ships
as a container image from ECR rather than a zip/layers bundle — see
[ADR 0001](adr/0001-lambda-container-image-packaging.md) for why (it began
as a Tesseract-packaging decision, but every stage's image follows the same
convention for local/production parity), and
[ADR 0011](adr/0011-extract-stage-alt-base-image-and-lambda-count.md) for
where that decision landed once implementation started.

### 2. Extract, by chamber and filing kind

A Filing's raw bytes get turned into structured `Filing` and `Transaction`
rows here — a House Filing routes to a digital-PDF parser or a scanned
(OCR) parser depending on which kind of document it is; a Senate Filing
goes to the one HTML extractor there is, since Senate has no
digital/scanned split.

- **House digital.** Text-layer PDFs are parsed by validating printed field
  labels before trusting the value beside them, rather than reading a fixed
  line offset — see
  [ADR 0003](adr/0003-digital-parser-label-validated-positional-walk.md)
  for why a positional-only walk was rejected.
- **House scanned.** Paper-form PTRs need OCR, which reliably recovers
  asset name and dates but not the transaction-type or value-range
  checkboxes. Those fields come back null with low confidence rather than
  guessed — an honest-null precedent, not a defect — per
  [ADR 0002](adr/0002-scanned-filing-fields-null-not-zonal-ocr.md).
- **Senate HTML.** The one Senate `/ptr/` page format has no document id of
  its own to cross-check against, and renders an Exchange as a single row
  with two asset lines rather than a structured split. Both are deliberate,
  narrower guarantees than the House path gets — see
  [ADR 0013](adr/0013-senate-html-extraction-design.md).

Every row extracted is kept regardless of asset type; this stage routes and
serializes, it never filters a row out.

### 3. Ticker resolution and LLM fallback

A `Transaction` with a still-null `ticker` (after the extractor's own
printed-symbol match) goes through an OpenFIGI + EDGAR resolution cascade.
Separately, an optional LLM fallback stage can recover specific null fields
from a Filing's own source text — gated per field on the evaluation
harness's current accuracy for that field and kind, so it only runs where
the extractor is measurably weak, never unconditionally on every null.

### 4. Quality gate

A per-run quality gate exists as a set of pure checks over a run's
aggregate statistics — a volume-regression check, a completeness check
against fields that should never be null, and a row-count-divergence
check against the collector's own announced count. It's designed to let a
caller skip a Silver overwrite when a run looks unhealthy, without ever
touching S3 or a prior-run store itself. **Implementation note:** as of
this writing, no Lambda handler calls this gate yet — it's implemented and
tested as a pure function, but the orchestration wiring to invoke it
automatically on every run is still open. Treat this stage as designed but
not yet load-bearing in production.

### 5. Silver write

`Filing` and `Transaction` rows are serialized to Hive-partitioned Parquet
(`silver/<table>/chamber=.../year=...`), one `part-<doc_id>.parquet` file
per Filing per table, so reprocessing a Filing overwrites its own file
instead of duplicating rows. No compaction job runs — at current House/
Senate volume, many small part files per partition is an accepted cost, not
a problem being solved yet. See
[ADR 0008](adr/0008-silver-storage-stays-parquet-part-per-doc-id.md).

**Implementation note:** ticker resolution, LLM fallback, and the Silver
write all currently happen inside the extract Lambda's own handler for the
House path — there's no separate "silver-write" Lambda, because no
independent behavior exists at that seam yet (see
[ADR 0011](adr/0011-extract-stage-alt-base-image-and-lambda-count.md)).
The Senate HTML extractor is implemented and covered by its own evaluation
set, but the extract Lambda's handler does not yet dispatch a Senate bronze
key to it — that dispatch wiring is open follow-up work, distinct from the
extractor itself.

## System architecture

The diagram below covers the AWS services involved: EventBridge triggers
the collector Lambdas on a schedule, House and Senate both land in the same
S3 Bronze bucket, every collector enqueues its own written keys onto the
extract Lambda's SQS queue (ADR-0016), which extract picks up and writes to
S3 Silver, every Lambda's image comes from ECR, GitHub Actions deploys the
Terraform stack through an OIDC-federated IAM role (never long-lived AWS
keys), and a tag-filtered AWS Budget publishes spend alerts through SNS.

<!-- TODO: diagrams/assets/architecture-system.svg (and its raw HTML source)
still show extract picking up Senate via an S3 event notification —
ADR-0016 removed that bridge; every collector enqueues onto SQS directly
now, including Senate's two paths. Needs a re-render. -->

![System architecture: EventBridge-scheduled Lambdas write filings to S3
Bronze; an extract Lambda reads from SQS and writes to S3 Silver, alongside
ECR, IAM/OIDC and SNS budget
alerting](diagrams/assets/architecture-system.svg)

See [ADR 0009](adr/0009-terraform-module-structure-and-cicd.md) for the
Terraform module layout and CI/CD posture this diagram reflects, and
[ADR 0012](adr/0012-terraform-root-stack-wiring.md) for how the root stack
wires bucket naming, the S3-event scope, and the SSM secret handoff.

## Bronze-to-Silver data flow

The diagram below shows the same journey by pipeline stage rather than by
AWS service: House and Senate each collect and extract independently, both
converge on the shared ticker-resolution/LLM-fallback/quality-gate stage,
and a shared Silver write serializes the result.

![Bronze to silver data flow: House and Senate collect and extract
independently, both pass through a shared ticker/LLM-fallback/quality-gate
stage, then a shared silver write serializes filings and
transactions](diagrams/assets/architecture-data-flow.svg)

## Diagram sources

Both diagrams were built with the repository's `diagram-design` skill.
Editable HTML sources (inline SVG, no external dependencies besides Google
Fonts) live under [`diagrams/raw/`](diagrams/raw/); the rendered SVG assets
embedded above live under [`diagrams/assets/`](diagrams/assets/). Update a
diagram by editing its `raw/*.html` source and re-exporting the SVG next to
it — see the skill's `references/export.md` for the exact procedure.
