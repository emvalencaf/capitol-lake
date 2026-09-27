# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Entries are added
under `Unreleased` in the PR that makes the change, and moved under a dated
heading when `development` is released to `master`.

## [Unreleased]

## [1.0.0] - 2026-09-27

### Added

- `extract_data.llm_extract.extract_llm` (#89): a benchmark-only extractor
  that reads a House PTR's transactions directly via an LLM (Groq, Gemini,
  or a local LM Studio model), distinct from the existing per-field
  `llm_fallback` stage (ADR 0019). `scripts/run_house_eval.py` gains
  `--extractor {tesseract,llm}`, `--provider {groq,gemini,lm_studio}`,
  `--model`, `--llm-input {text,vision}`, `--llm-runs` (a consistency check
  across repeated extractions, replacing the determinism check for LLM
  output) and `--sample`, so a small LLM can be benchmarked against
  Tesseract on the same gold set and report format.
- `shared.llm_providers`: every Groq/Gemini call is now paced to its
  model's free-tier limit (`RateLimiter`/`_rate_limiter_for`) before it's
  sent, so a multi-filing `run_house_eval.py --extractor llm` run no longer
  self-inflicts a 429 cascade by firing filings back-to-back faster than
  the free tier allows. This is pacing, not retrying — still exactly one
  attempt per filing, so it doesn't conflict with ADR 0019's "no automatic
  retries on a provider failure." Pacing intervals are sourced from Groq's
  own rate-limits table plus one empirically-observed sub-limit
  (`qwen/qwen3.8-27b`'s free tier caps output tokens far below its
  documented TPM) and, for Gemini, from a live 429 naming its real
  constraint as a 20-requests-per-day-per-model quota rather than a
  per-minute one.
- `scripts/setup-github-env.sh`: `up`/`down` script that automates
  `infra/README.md`'s "One-time GitHub setup" step via `gh` — creates or
  removes the `production` GitHub Environment (with a required-reviewer
  gate) and the `AWS_ROLE_ARN`/`TF_STATE_BUCKET`/`FINOPS_ALERT_EMAIL` repo
  secrets `infra-cicd.yml` reads. `down --purge-history` additionally
  deletes the workflow's run history and the Environment's deployment
  records.

### Fixed

- `infra/bootstrap/oidc.tf`: the GitHub Actions OIDC trust policy and the
  `terraform-apply` IAM role's own permissions never actually worked end to
  end — `infra-cicd.yml`'s `plan`/`apply` jobs 403'd on `AssumeRoleWithWebIdentity`
  because this repo has "immutable subject claims" enabled
  (`repo:<owner>@<owner_id>/<repo>@<repo_id>:...` instead of the classic
  `repo:<owner>/<repo>:...` GitHub `sub` format the trust policy's condition
  assumed), and once that was fixed, `terraform plan` surfaced a long tail of
  IAM gaps only exercisable once OIDC actually worked: the main stack's
  single `capitol-lake` bucket doesn't match the `capitol-lake-*` resource
  pattern the policy required; the EventBridge/CloudWatch-alarm statements
  only covered one of the two schedules/alarms `modules/scheduling` and
  `modules/finops` each create; Lambda event source mappings (UUID-named,
  not `capitol-lake`-prefixed) had no statement at all; and several read-only
  actions (`sns:GetSubscriptionAttributes`, `s3:GetBucketAcl`/`GetBucketCORS`/
  etc., `budgets:ListTagsForResource`, `ssm:DescribeParameters`,
  `lambda:ListTags` on event source mappings) were missing outright. Verified
  by rerunning the `plan` job against `chore/setup-github-env-script`'s PR
  until it passed clean.
- `shared.llm_providers`'s Gemini provider: `extract_llm`'s schema uses
  JSON Schema's `{"type": ["string", "null"]}` nullable-union form, which
  Gemini's `responseSchema` rejects outright (a 400: "Proto field is not
  repeating, cannot start list") — every Gemini call failed before this.
  `_to_gemini_schema` now converts it to Gemini's OpenAPI-subset form
  (`{"type": "string", "nullable": true}`, recursively through
  `properties`/`items`) before the call is sent. Also switched the default
  Gemini model from `gemini-2.0-flash` (retired by Google; a live call now
  404s) to `gemini-2.5-flash`, the newest model still on a workable free
  tier.

### Changed

- `src/`: split the single `src/capitol_lake` package into `src/shared/`
  (code used by more than one Lambda image) plus one top-level package per
  Lambda (`house_collect`, `senate_collect`, `senate_collect_automated`,
  `senate_akamai_probe`, `extract_data`, `stub`), each with its own
  `handler.py` (ADR-0014). Every `docker/*.Dockerfile` now `COPY`s `shared`
  plus its own package only, instead of the whole tree, so a Lambda's image
  can no longer carry another Lambda's code. `pyproject.toml` lists all
  seven packages under `[tool.hatch.build.targets.wheel]`. `CODE_STANDARDS.md`
  updated to document the new layout.
- `tests/`: partitioned into `tests/units/` (every existing test, moved to
  mirror the new `src/` layout — none of them touch live network, S3, or a
  real Lambda) and `tests/e2e/` (empty scaffold for future real-runtime
  tests, see `tests/e2e/README.md`).
- `infra-cicd.yml`: `AWS_ROLE_ARN`, `TF_STATE_BUCKET`, and `FINOPS_ALERT_EMAIL`
  moved from repository variables to repository secrets, so GitHub masks them
  in Actions logs ahead of the repo's planned move to public (ADR-0009's
  "public Phase 3" rationale for OIDC applies here too — a role ARN and
  bucket name aren't credentials on their own, but they're not meant to be
  world-readable log output either). `infra/README.md`'s setup instructions
  updated to match.
- `infra/modules/storage`: collapsed the separate bronze/silver S3 buckets
  into a single project bucket, with bronze/silver as key prefixes
  (`bronze/...`/`silver/...`, already how `shared/keys.py` builds keys, so no
  Lambda code changed). `modules/pipeline`'s IAM policies now scope
  `BronzeReadWrite`/`BronzeList`/`SilverWrite` to the matching prefix instead
  of a whole separate bucket. `modules/pipeline`'s ECR repositories also gained
  `force_delete = true` (matching `probes/senate-akamai-probe`), so
  `terraform destroy` no longer fails with `RepositoryNotEmptyException` on a
  repo still holding pushed images.
- `src/shared/wide_event.py`: added a wide-event (canonical log line) logger,
  `.claude/skills/logging-best-practices`. Every real pipeline handler
  (`house_collect`, `senate_collect`, `senate_collect_automated`,
  `extract_data`) now wraps its body in `wide_event(stage, context)`, which
  emits exactly one JSON log line per invocation with the Lambda's identity
  (`function_name`/`function_version`/`aws_request_id`/region), timing, and
  outcome, plus whatever business fields the handler adds (counts written/
  enqueued/processed, `noop`, per-record failures for `extract`'s SQS batch
  path). No commit hash yet — nothing currently tags a deployed image with
  one; a follow-up could add that via CI. `senate_akamai_probe` and `stub`
  are intentionally left out: the former is a throwaway hand-invoked probe,
  the latter isn't wired into `infra` at all.
- `collect_house`/`collect_senate`/`run_senate_efd_session`: an optional
  `on_progress` callback, called after every entry with `{"index", "total",
  "doc_id", "action"}` (`action` straight from `bronze_write`'s own plan:
  `"write"` or `"noop"`). Wired through each handler into
  `shared/wide_event.py`'s new `log_progress()`, which emits one JSON log
  line immediately per entry — unlike `wide_event`'s single end-of-run
  summary, so CloudWatch shows activity throughout a run that can approach
  the Lambda's 900s timeout instead of looking hung until the very end. The
  pure collect functions stay side-effect-free and unit-tested; only the
  handler decides the callback becomes a log line.
- `extract_data/handler.py`: `_process_one` now reports `llm_fallback_used`
  (whether `_build_llm_fallback`'s gates actually let the LLM fallback run
  for that filing) and the batch-processing loops (`batch_no_sqs`,
  `sqs_batch`) emit a `log_progress()` line per record — including a
  `failed`/`error` line for a caught per-record exception before it becomes
  a `batchItemFailures` entry — mirroring the visibility the collectors
  already had, since `extract` can run just as long per batch (OCR, ticker
  resolution, LLM fallback network calls).
- `senate_collect`/`senate_collect_automated`: both now enqueue their own
  `extract_queue_message` per bronze key written, exactly like
  `house_collect` (ADR-0016, supersedes ADR-0015). Removes
  `infra/modules/scheduling`'s bronze-bucket-to-SQS bridge
  (`aws_s3_bucket_notification`, `aws_sqs_queue_policy`, and the variables
  that only existed to wire it: `bucket_id`, `bucket_arn`,
  `extract_queue_arn`, `extract_queue_url`, `senate_bronze_prefix`,
  `senate_bronze_suffix`) and the nested S3-notification-via-SQS envelope
  `shared/orchestration.py` had to unwrap — an SQS record's body is always
  `{"bronze_key": ...}` now. Each Senate collector's IAM role gained its own
  `sqs:SendMessage` policy scoped to extract's queue (mirroring
  `house_collect_sqs`). Also fixed `house_collect`/`senate_collect`'s wide
  event logging the full `noop` key list instead of a `noop_count` (an
  inconsistency introduced alongside the wide-event work above), and added
  `docs/research/house-ptr-amendment-doc-id-behavior.md`: primary-source
  research (House Clerk PTR form/instructions, the live annual index) found,
  with high confidence, that a House PTR correction always gets its own new
  DocID rather than silently replacing an existing one's content — context
  for why `collect_house`'s hash-compare re-fetch is a defensive, not yet
  empirically-required, safeguard.
- `collect_house`: acting on that research, a `doc_id` already on record is
  now skipped with **no fetch at all** — no HTTP call, no
  `rate_limiter.wait()`, no re-hash — instead of being re-downloaded every
  run just to confirm its hash is unchanged (ADR-0017). Only a never-seen
  `doc_id` gets fetched and written. `collect_house`'s return dict's `noop`
  key is renamed `skipped` (there's no hash comparison happening to call a
  no-op any more), `on_progress`'s `action` is `"skip"` instead of
  `"noop"`, and `house_collect/handler.py`'s wide-event field is
  `skipped_count`. Scoped to House only; Senate's two collectors still
  hash-compare on every run.
- `collect_house`/`collect_senate`/`run_senate_efd_session`: replaced the
  per-entry `read_existing_sha256` (one `s3:GetObject` per index entry, just
  to test existence) with a `known_doc_ids: Callable[[], set[str]]` called
  once per run — each handler implements it as a single paginated
  `s3:ListObjectsV2` over the relevant bronze prefix, parsed through
  `shared.keys.parse_bronze_key` into a `set` (ADR-0018). House's listing is
  scoped to the run's own year (`bronze/house/year=<year>/`); both Senate
  collectors list the whole `bronze/senate/` prefix, since a captured
  response or lookback window can span a year boundary.
- **Senate now skips a known filing UUID too**, exactly like House
  (ADR-0018): `collect_senate` and `run_senate_efd_session` (the latter also
  skipping the browser page navigation and Akamai classification for it,
  not just the write) both trust a known UUID as immutable, with no fetch
  and no rate-limit charged. Unlike House, this is **not** backed by
  primary-source research — it rests on this repo's own pre-existing,
  unverified assumption that a Senate eFD amendment always gets a separate
  UUID. `SenateEfdSessionResult.noop` renamed `.skipped`;
  `senate_collect`/`senate_collect_automated`'s wide-event fields are
  `skipped_count`.
- `docs/architecture.md`, `docs/diagrams/`: updated the Collect stage
  description and re-rendered `architecture-system.svg` to match the two
  changes above — the known-`doc_id`/UUID skip (ADR-0017/0018) and the
  wide-event/per-item-progress logging (`src/shared/wide_event.py`) — and
  fixed the system diagram, which still showed separate Bronze/Silver S3
  buckets and a Senate-only S3-event trigger; both are now one bucket with
  `bronze/`/`silver/` prefixes and every collector enqueues onto SQS
  directly (ADR-0016).

### Removed

- `senate_akamai_probe` (`src/senate_akamai_probe/`,
  `infra/probes/senate-akamai-probe/`, `docker/senate_akamai_probe.Dockerfile`,
  `scripts/deploy-senate-akamai-probe.sh`, `tests/units/senate_akamai_probe/`):
  retired the throwaway probe now that #29's question is answered (PASS) and
  #67 moved its reusable logic (the agreement-click flow,
  `classify_probe_result`) into `src/shared/senate_efd_classification.py` and
  `src/senate_collect_automated/`. Its AWS Lambda, ECR repository, and IAM
  role were torn down and confirmed gone before deletion. `pyproject.toml`'s
  `[tool.hatch.build.targets.wheel].packages` no longer lists it.
  `docs/local-dev.md` and `docs/research/senate-akamai-lambda-probe.md`
  updated to stop pointing at it as live infra.

### Fixed

- `docker/extract-requirements.txt`: missing `beautifulsoup4`/`lxml`, so
  `extract`'s Lambda failed cold start with `Runtime.ImportModuleError:
  No module named 'bs4'` (`extract_data/extract.py` imports
  `extract_data/senate_extract.py`, which parses Senate HTML filings via
  `BeautifulSoup(..., "lxml")`, ADR-0013). This file mirrors
  `pyproject.toml`'s runtime deps by hand for the non-AWS base image
  (`docker/extract.Dockerfile`'s Tesseract requirement) and drifted out of
  sync when Senate HTML extraction was added. Verified by building the
  image and importing `extract_data.handler` inside it.
- `infra`/`shared/orchestration.py`: Senate's bronze-to-extract chain
  invoked `extract`'s Lambda directly off an S3 event notification, with no
  SQS message behind it — unlike House, which chains over extract's own SQS
  queue. A failed Senate-triggered extract therefore had nothing to retry or
  dead-letter (`BronzeKeyRecord.message_id` was always `None` for an
  S3-sourced record). The bronze bucket's S3 notification now targets
  extract's own SQS queue instead (an `aws_sqs_queue_policy` scopes
  `s3.amazonaws.com`'s `sqs:SendMessage` to the bucket's ARN);
  `bronze_key_records_from_event` was extended to unpack an SQS record
  whose body is a forwarded S3 notification, pairing every bronze key it
  finds with the outer SQS record's `messageId` (ADR-0015).
- `infra`: `house-collect`'s Lambda timeout was left at the `lambda-stage`
  default (60s), which times out mid-run (`Sandbox.Timedout`) on a
  full-year backfill — confirmed via `scripts/invoke-collectors.sh house`:
  it wrote 5 filings to Bronze in the 60s window before hitting the limit,
  against a ~500 filings/year backlog (`docs/cost.md`) at roughly 1/s.
  Bumped to 900s (Lambda's ceiling, matching `senate-collect-automated`'s
  existing timeout) — day-to-day runs against the daily schedule's small
  trickle of new filings finish in well under that.
- `infra`: `house-collect`/`senate-collect`/`senate-collect-automated`'s IAM
  role was missing `s3:ListBucket` on the Bronze bucket (only had
  `GetObject`/`PutObject` scoped to `bronze/*`). Each collector's
  idempotent-skip check GetObjects a meta key that legitimately doesn't
  exist yet on a filing's first run; without `ListBucket`, S3 can't
  distinguish that caller from one probing for the key's existence, so it
  returns 403 `AccessDenied` instead of 404 `NoSuchKey` — failing every
  first invocation. Added a `BronzeList` statement granting `ListBucket` on
  the bucket itself (not `/*`) to the 3 collector roles.

### Added

- `scripts/invoke-collectors.sh`: manually invokes `capitol-lake-house-collect`
  and/or `capitol-lake-senate-collect-automated` (normally
  EventBridge-scheduled on `rate(1 day)`, so a fresh deploy's first real run
  is otherwise up to 24h away) — prints the invoke result, tails recent
  CloudWatch logs, and lists what landed under the Bronze bucket's
  `bronze/house/`/`bronze/senate/` prefixes.
- `infra`: new `var.stage_reserved_concurrency` (root and `modules/pipeline`,
  default `-1`, i.e. unreserved) makes each stage Lambda's reserved
  concurrency overridable, and changes the default from the prior hardcoded
  5-per-stage to unreserved, matching this project's demonstrative scope. A
  fresh AWS account's default Lambda concurrent-executions quota can sit
  below the ~30 units 4 stages at 5 apiece would need while keeping AWS's
  mandatory 10-unit unreserved floor, which fails every stage's `terraform
  apply` with "decreases account's UnreservedConcurrentExecution below its
  minimum value of [10]" unless a Service Quotas increase is requested
  first — `infra/README.md` documents this and how to opt back into
  reserved concurrency (`stage_reserved_concurrency = 5`) if this ever
  carries real production traffic.
- `scripts/deploy-infra.sh`: automates the main stack's first-deploy
  chicken-and-egg problem — every pipeline Lambda points at
  `<its ECR repo>:latest`, which doesn't exist until an image is pushed, so a
  plain `terraform apply` on a fresh account fails with "Provide a valid
  source image." The script applies the ECR repos only, builds and pushes
  each of the 4 stages' images, applies the rest of the stack, then forces
  each Lambda onto the just-pushed image (working around `:latest` not
  registering as a Terraform diff) — the same dance
  `scripts/deploy-senate-akamai-probe.sh` already automated for the
  standalone probe Lambda. `infra/README.md` updated to reference it.
- Root README: links from About The Project, Getting Started, and Usage to
  `docs/architecture.md`, `docs/cost.md`, `docs/metrics.md`, and
  `infra/README.md`. No new top-level section; existing structure, the
  `readme-top` anchor, and back-to-top links are unchanged. (#81)
- `.wiki/` current-state concepts (28 concepts, `okf_validate.py --strict`
  passing): an architecture-overview concept indexing `docs/architecture.md`
  and its five pipeline-stage concepts (collect, extract, ticker
  resolution/LLM fallback, quality gate, Silver write); twelve domain-term
  concepts covering `CONTEXT.md`'s vocabulary (disclosures, dates, layers);
  and one decision concept per existing ADR (0001, 0002, 0003, 0008, 0009,
  0010, 0011, 0012, 0013), summarizing each's decision and cross-linking back
  to the ADR file rather than restating its reasoning. Purely additive from
  current state forward, no `backfill` run. (#80)
- `docs/metrics.md`: extraction-accuracy metrics doc sourced from the
  `eval/` harness (per-field scores for House digital, House scanned,
  Senate HTML) and this changelog. Every number is labeled eval-harness/
  gold-set data with an explicit statement that the pipeline has never run
  against real AWS infrastructure; the scanned-House column's uniform 0.10
  is called out as a tesseract-absence extraction-failure artifact (this
  sandbox has no `tesseract` binary), not a real accuracy figure. House
  digital numbers come from a fresh re-run rather than `eval/README.md`'s
  own first-run snapshot, which predates #57's fix (#65) and is now stale
  (all 30 digital filings extract successfully today, not 28). (#78)
- `docs/cost.md`: AWS cost estimate built from a real
  [AWS Pricing Calculator](https://calculator.aws) estimate (shareable link
  included), splitting fixed scheduling cost (House/Senate collector
  Lambdas, 365 EventBridge invocations/year each) from per-filing processing
  cost (`extract`'s ticker/LLM-fallback/silver-write, S3, SQS). House volume
  cited to ADR 0008 (~451-515 PTRs/year); Senate volume derived from
  `eval/README.md`'s 661-match eFD search window and labeled an estimate
  (~55-60 PTRs/year). Embeds a `diagram-design` bar chart of estimated cost
  by stage (`docs/diagrams/raw/cost-by-stage.html` /
  `docs/diagrams/assets/cost-by-stage.svg`). Notes that EventBridge's
  default-bus rules aren't billed, that ECR image storage/lifecycle is
  excluded by deliberate choice given the project's demonstrative scope, and
  that real invocation durations are assumed pending deployment. (#77)
- `docs/architecture.md`: narrative architecture overview of the pipeline
  (House/Senate collect, extract routing, ticker/LLM fallback, quality
  gate, Bronze -> Silver writes), cross-referencing ADRs 0001, 0002, 0003,
  0008, 0009, 0011, 0012 and 0013. Embeds two `diagram-design` diagrams: an
  AWS system architecture diagram and a Bronze -> Silver data-flow diagram
  by pipeline stage. Editable sources live under `docs/diagrams/raw/`,
  rendered SVG assets under `docs/diagrams/assets/`. (#76)
- `extract_senate_filing` (`stages/extract.py`), a Senate counterpart to
  `extract_house_filing`: parses a Senate `/ptr/` filing page
  (`stages/senate_extract.py`, new `beautifulsoup4`/`lxml` dependency) and
  serializes it to the same silver Parquet shape. No digital/scanned duality
  to route on (only clean HTML `/ptr/` pages are collected), so `kind` is
  always `"html"`. Per ADR 0013: unlike House, the page carries no doc id of
  its own to cross-check against the bronze key, so `doc_id` is taken as
  given; an `Exchange` row's two-line asset cell (asset given up, asset
  received) becomes one `Transaction` with the given-up asset in
  `asset_description` and the received asset's text in `description`, and
  `notification_date`/`filing_status`/`sub_owner` stay null with no
  structured source to read them from. Chamber routing into a shared
  `extract` entry point / `extract_handler.py` is deferred to a follow-up.
- A 40-filing hand-labelled gold set for `extract_senate_filing`
  (`eval/senate_fixtures/`, `eval/senate_gold/`, `scripts/run_senate_eval.py`),
  parallel to the House one (see `eval/README.md`'s "Senate gold set"
  section): real `/ptr/` pages fetched live, scored a perfect 1.00 on every
  field after fixing two real gaps the single hand-built test fixture never
  exercised — a private-stock row's asset cell can carry two `text-muted`
  divs (`Company:`/`Description:`), only the first of which
  `_parse_asset_cell` originally kept, and a stray double space in the
  source's own printed data wasn't whitespace-collapsed into
  `asset_description` like every other field already was. Both fixed in
  `senate_extract.py` with new unit test coverage, not deferred.
- Deploy the automated Senate collector on a daily schedule (#69):
  `infra/modules/pipeline`'s `senate_collect_automated` Lambda mirrors
  `house_collect`/`senate_collect`'s shape (own ECR repo, own IAM role,
  `memory_mb = 2048`/`handler_timeout_seconds = 900` for a real Chromium
  session) with no SQS trigger, since the bronze bucket's existing S3-event
  notification into `extract` already fires for its writes regardless of
  which Senate path produced them. `infra/modules/scheduling` gets a new
  `rate(1 day)` EventBridge schedule for it, mirroring House's. A dedicated
  `aws_cloudwatch_metric_alarm` in `infra/modules/finops` watches its own
  Errors metric on a short period (unlike House's multi-day staleness
  dead-man's-switch) so a single blocked/failed run alerts the same day,
  through the existing `capitol-lake-budget-alerts` SNS topic.
- Automated Senate collector Lambda handler and image (#68):
  `handlers/senate_collect_automated_handler.py` wires #67's
  `run_senate_efd_session` flow to a real `boto3` S3 client, following the
  same thin/untested handler convention as every other stage; it takes no
  `event["response"]` capture since the browser session drives the search
  itself, and never enqueues an SQS message (Senate has no schedule to chain
  from, per #18). `docker/senate_collect_automated.Dockerfile` packages it
  like `docker/senate_akamai_probe.Dockerfile`'s alternative-base pattern
  (`python:3.12-slim` + `awslambdaric` + `aws-lambda-rie` + Playwright
  Chromium with `PLAYWRIGHT_BROWSERS_PATH` pinned) rather than the plain
  `docker/lambda.Dockerfile` base, since Playwright's Chromium needs real
  shared libraries the AWS base image's minimal userland doesn't carry.
  Demoed locally via RIE against MinIO (`senate-collect-automated-stage` in
  `docker-compose.yml`, port 9104), per `docs/local-dev.md`: a real
  invocation wrote a real bronze object and its `.meta.json` sidecar,
  verified directly in MinIO. No AWS infra, schedule, or real deploy yet
  (later ticket).
- Senate eFD PTR search-and-fetch session (#67): `capitol_lake.browser.senate_efd_session`
  drives one authenticated Playwright session through the full flow —
  warm-up navigation, the `prohibition_agreement` gate accepted via a real
  click, the PTR search form submitted for a 7-day lookback window, the
  resulting DataTables JSON routed through `parse_senate_index`, up to 300
  `/ptr/` filings fetched via real page navigations in the same session
  and written through `bronze_write`. Any response other than `"cleared"`
  (the search response or a filing fetch) raises `SenateEfdBlockedError`
  immediately, with enough context to diagnose from a log; filings already
  written before that stay written. `classify_probe_result` moved here
  permanently from `capitol_lake.probes.senate_akamai_probe` (re-exported
  there unchanged) alongside the new `classify_search_response` for the
  search endpoint's own JSON. Pure-mechanics layer only — no Lambda
  handler, no infra, no Docker yet. Hand-tested against the live site; see
  `docs/research/senate-efd-session-hand-test.md`. Feeds #28's Senate
  collector automation.
- Senate-Akamai Lambda-egress probe (#29, run and resolved — **result:
  PASS**): `capitol_lake.probes.senate_akamai_probe` drives one real
  headless-Playwright request (warm-up navigation, the site's own
  `prohibition_agreement` gate accepted via a real click, then the target
  filing) at a Senate eFD `/ptr/` filing and classifies the response as
  `cleared`/`blocked_akamai`/`blocked_other`/`ambiguous`; run live from a
  real AWS Lambda (`infra/probes/senate-akamai-probe/`, standalone
  Terraform, since torn down) via
  `docker/senate_akamai_probe.Dockerfile` and
  `scripts/deploy-senate-akamai-probe.sh` (build/push/apply/invoke/destroy).
  Confirmed a Lambda-origin request clears the Akamai bot/fingerprint check
  the same way #23's local-network probe did, once the automation replicates
  the real access flow — see `docs/research/senate-akamai-lambda-probe.md`
  for the full attempts log and evidence. Unblocks #28's Senate collector
  automation design decision.
- CI/CD for `infra/` via GitHub Actions and OIDC (#46), per ADR-0009:
  `.github/workflows/infra-cicd.yml` runs `terraform plan` on pull requests
  touching `infra/**` and `terraform apply` on push to `master`, authenticating
  to AWS through a federated OIDC role — no long-lived access keys stored as
  repo secrets. `apply` runs through a `production` GitHub Environment
  (required-reviewer approval gate, configured by hand in repo settings).
  `infra/bootstrap` now also provisions the GitHub OIDC provider and the one
  IAM role both jobs assume, scoped by resource-name prefix/fixed name to
  just the resource types the main stack manages, not
  Administrator/PowerUserAccess.
- FinOps Terraform module + staleness health check (#45), per ADR-0010:
  `infra/modules/finops` defines an AWS Budget filtered to the
  `Project=capitol-lake` cost allocation tag (not account-wide), alerting at
  50%/80%/100% of actual spend plus a forecasted->100% threshold, all through
  a dedicated `capitol-lake-budget-alerts` SNS topic with an email
  subscription (`var.finops_alert_email`, no default). The same topic backs
  a `aws_cloudwatch_metric_alarm` dead-man's-switch on `house-collect`'s
  `Invocations - Errors` metric math: two consecutive periods of
  `var.house_schedule_period_seconds` (default 86400s, matching
  `rate(1 day)`) with zero successful runs, `treat_missing_data = "breaching"`
  so a Lambda that stops being invoked entirely still alarms. `common_tags`
  gained `Environment` (`"production"`, ADR-0009's single-environment
  scoping) and `Chamber` (default `"n/a"`), with `infra/modules/pipeline`
  overriding `Chamber` to `"house"`/`"senate"` on the two chamber-specific
  stage resources. `terraform validate`/`fmt` are clean and `terraform plan`
  succeeds with 0 errors against a local backend and mocked AWS credentials
  (real S3 backend/account access is out of scope, per #44's precedent).
  Activating the `Project` cost allocation tag in the Billing Console remains
  a manual, one-time step outside Terraform's reach (ADR-0010's Consequences).
- Terraform core infra (#44), wiring `infra/modules/lambda-stage` (#43) into
  a deployable root stack per ADR-0009/ADR-0011: `infra/bootstrap` (one-time,
  local-state S3 state-bucket bootstrap), `infra/modules/storage`
  (bronze/silver buckets), `infra/modules/pipeline` (ECR repositories, IAM
  roles/policies, SSM `SecureString` secret parameters, and the three
  `lambda-stage` instances — `house-collect`, `senate-collect`, `extract`),
  `infra/modules/scheduling` (House's EventBridge schedule end-to-end;
  Senate's `bronze/senate/`-prefixed S3-event trigger straight into
  `extract`, scoped to avoid double-processing House filings, which already
  chain via SQS), and a root module composing all four. State uses S3-native
  locking, no DynamoDB. ADR 0012 records the wiring decisions this needed
  beyond ADR-0009/ADR-0011 (bucket naming, the SSM secret handoff shape,
  S3-event scoping, and the static-year schedule input) and what's
  deliberately left for follow-up (populating secrets, pushing images,
  wiring `extract_handler.py` to actually read SSM at runtime).
  `infra/modules/lambda-stage` gained a `function_name` output the
  scheduling module's `aws_lambda_permission` resources need.
  `terraform validate` is clean for the root module and `infra/bootstrap`;
  `terraform plan` was verified as far as possible without a real AWS
  account (passes all config/schema checks, fails only at the provider's own
  `sts:GetCallerIdentity` call against a fake credential). FinOps (#45) and
  the CI/CD OIDC apply workflow (#46) are separate, later tickets.
- Orchestration: Lambda handlers wired to an SQS chain, plus the extraction
  stage's container image (#43), implementing the shape #18 settled.
  `src/capitol_lake/stages/orchestration.py`'s `bronze_keys_from_event` is
  the one place a handler unpacks its event, dispatching on shape: a plain
  `{"bronze_key": ...}` invocation (kept for manual/RIE testing, every
  handler still accepts it), an SQS event (each record's JSON `body` is
  `extract_queue_message`'s `{"bronze_key": ...}`), or an S3 event (each
  record's own `s3.object.key`, URL-decoded) — the entry point for the
  Senate side, which has no scheduled collector to send an SQS message on
  its behalf; once its `write_bytes` lands a bronze object, a bucket-level
  S3 event notification (infra) triggers extract directly, whether the
  object came from a real Lambda invocation or a human's manual upload.
  `bronze_key_records_from_event` pairs each key with that record's SQS
  `messageId` (`None` for a plain/S3 record), so a handler's per-message
  failure reporting doesn't need to re-derive which records came off SQS
  itself — including safely in a batch that mixes sources, which an earlier
  version of this handler got wrong (a `record["messageId"]` lookup on a
  non-SQS record would have raised `KeyError`; caught and fixed during this
  issue's own code review, see `tests/test_orchestration.py`). `keys.py`
  gains `parse_bronze_key` (chamber/year/doc_id back out of a bronze key),
  promoted from a private helper `stages/extract.py` used to duplicate,
  since it's now shared with `orchestration.py`.
  `house_collect_handler.py` enqueues one SQS message per bronze key
  `collect_house` actually wrote this run (never a `noop` key) to
  `EXTRACT_QUEUE_URL`, left unset by default so the handler still runs
  standalone. `extract_handler.py` now accepts a batch of SQS records
  (batch size 1 in production) and reports a per-message failure via
  `batchItemFailures` (`ReportBatchItemFailures`) so one filing's exception
  doesn't fail the whole batch, verified live end-to-end against a real
  House PTR fixture through MinIO + ElasticMQ (local SQS emulation, chosen
  over LocalStack since its SQS coverage is Hobby-plan/non-commercial-only
  per `docs/research/free-tool-inventory.md`, #4) via the Lambda Runtime
  Interface Emulator; a plain or S3-event invocation still lets an
  exception raise, matching every other handler. `docker/extract.Dockerfile`
  resolves ADR-0001's deferred Tesseract-packaging item: neither the AWS
  Lambda Python base image's nor plain `amazonlinux:2023`'s `dnf` repos
  carry a `tesseract` package at all, so this stage instead uses AWS's
  documented "alternative base image" pattern (`python:3.12-slim`,
  `apt-get install tesseract-ocr` — the same package CI already installs —
  `awslambdaric` via `pip`, and a separately-installed `aws-lambda-rie` for
  local testing, wired by `docker/extract-entrypoint.sh`); every other
  stage's image is unaffected. `infra/modules/lambda-stage` (Terraform,
  `terraform validate`-clean, not yet wired into a root module) is the
  reserved-concurrency/DLQ-per-stage configuration the issue's acceptance
  criteria calls for. ADR 0011 records both packaging decisions and why the
  actual topology is three Lambdas, not the four #18 named: #41 had already
  folded ticker resolution and LLM fallback into `extract_handler.py`, and
  no silver-write business logic exists beyond the `put_object` calls
  already there, so `extract`'s queue carries the slower DLQ backoff #43
  asks for on the "ticker/LLM-fallback" stage.

- `src/capitol_lake/stages/quality_gate.py`: per-run quality gate (#42). `evaluate_quality_gate` combines three independent, pure checks over a `RunSummary` pair (prior run vs. current run, one summary per silver table) and never touches S3 or any prior-run store itself: `check_volume_regression` fails when the current run's `row_count` dropped more than a configurable threshold (50% default) from the prior run's; `check_completeness` fails when any field the caller's `RunSummary.null_counts` names (a design-intentionally-non-null one, per `schema.py`) had a null this run; `check_row_count_divergence` fails when `row_count` disagrees with the source-index-announced count, skipped when that count isn't known. A `GateResult.passed` is `True` only when none of the three failed, letting a caller decide whether to skip or proceed with the silver overwrite without invoking the orchestration layer (#43, out of scope here) — the pure-function seam the spec's testing decisions call for. Distinct from the gold-set evaluation metric (`evaluation.py`, #40): this gate reasons only about run-to-run operational health, never extraction accuracy.
- `src/capitol_lake/stages/llm_fallback.py`: LLM fallback stage (#41) — an optional, per-field structured-output recovery pass for a `Transaction` field the rule-based cascade left null or `LOW_CONFIDENCE`, gated two ways so it's never invoked unconditionally: `eligible_fields_from_scores` only admits a field whose macro-averaged score from the evaluation harness (`evaluation.score_gold_set`/`scripts/run_eval.py --json`, #40) is below a caller-supplied threshold, and `fields_needing_fallback` further narrows to fields actually null/low-confidence on a given transaction. The structured-output contract (`fallback_schema`) is built directly from `evaluation.SCORED_FIELDS` and the silver schema's own enum/date/number types — no separate DTO or translation layer; `apply_fallback_result` only coerces JSON scalars back to the schema's native types (enums, `date`, `float`, combining `value_min`/`value_max` into one `ValueRange`) and marks the touched fields `LLM_CONFIDENCE`, lowers `confidence` to match, and tags `Provenance.extractor` with a `+llm-fallback` suffix so a fallback-touched row is never indistinguishable from a purely rule-based one. Two entry points mirror ADR 0002's digital/scanned split: `apply_text_fallback` (digital, the PDF's own text) and `apply_vision_fallback` (scanned, directly on the page image — OCR text is the same lossy signal that produced the null, per the checkbox-grid finding in `scanned_extract.py`). Both take an injected `complete_text`/`complete_vision` callable, following this codebase's network-dependency-injection convention (`ticker_resolve.resolve_ticker`); `src/capitol_lake/llm_providers.py` wires concrete providers (LM Studio/Gemma as the free local default, Gemini and Groq as free-tier alternatives, Groq text-only since it hosts no free vision model), selected via the `LLM_FALLBACK_PROVIDER` env var with no code change to swap. `stages/extract.py`'s `extract_house_filing` gains an optional `llm_fallback(transaction) -> transaction` hook, applied to every row before ticker resolution, so a still-null `ticker`'s `asset_description`/`asset_type` can benefit from anything the fallback stage just recovered; a caller wires the hook to `apply_text_fallback`/`apply_vision_fallback` with whatever eligible-field set and provider it chooses. `handlers/extract_handler.py`'s `_build_llm_fallback` wires the digital path end-to-end: it's a no-op unless `LLM_FALLBACK_ENABLED` is set and an `LLM_FALLBACK_EVAL_REPORT` (the JSON `scripts/run_eval.py --json` produces) is found, and even then only touches fields that report's `by_kind["digital"]` scores below `LLM_FALLBACK_THRESHOLD` (default 0.8) — real, threshold-gated invocation, not just the tested primitive. The scanned/vision path is left unwired in the handler: `apply_vision_fallback` is implemented and tested, but which page image belongs to which transaction isn't tracked yet by `scanned_extract.ScannedExtraction`, and guessing would violate this project's own honest-null convention (ADR 0002); noted as follow-up rather than solved here. `llm_providers.py` performs real network I/O and is not unit-tested, per this repo's handler convention; the decision logic it wraps is tested against canned provider responses.
- `eval/`: the extraction evaluation harness (#40, closing #8's spec stories #23-#26). `eval/gold/` holds 40 hand-labelled House PTR filings (30 digital, 10 scanned, spanning 2021/2023/2024/2025), sampled from the House Clerk's public index and matched to their PDFs in `eval/fixtures/` (`manifest.json` records each fixture's `doc_id`/`year`/`kind`). Digital filings were labelled from pypdf's own generic `extract_text()` output (independent of this project's structural parser); scanned filings, which have no text layer, were labelled visually from rasterized page images since this sandbox has no working `tesseract` install — including reading the paper form's `transaction_type`/dollar-bracket checkboxes by eye, which `extract_scanned` cannot do (ADR 0002) and is expected to score near zero on. `src/capitol_lake/evaluation.py` scores a predicted `Transaction` row against its gold counterpart per field (`SCORED_FIELDS`; ticker and `Filing`-level metadata are excluded per the issue), matched by `line_no`: enums/dates/dollar amounts by exact match (both null counts as a match), free text by a continuous `difflib.SequenceMatcher` similarity ratio. `score_filing` averages across the union of a filing's gold and predicted line numbers, so both a missed gold row and a hallucinated predicted row (ADR 0002: "an honest zero rows... beats a fabricated one") score 0.0 on every field, even on a filing with zero gold transactions (a legitimate "nothing to report" PTR). `score_set`/`score_gold_set` macro-average filing scores by set (digital/scanned) and overall, the two-level "macro-averaged by filing then by set" the issue asks for. `scripts/run_eval.py` runs the current extractors against the gold set and prints the per-field report; a single filing's extractor exception is caught and scored as a total miss rather than aborting the whole run, and reported separately under "Extraction errors" — the harness's first real run this way surfaced a genuine `extract_digital` gap (a literal, non-bracket dollar amount crashes `parse_value_range`), filed as #57 rather than fixed here. The runner also performs the one-time repeat-run determinism check the issue asks for (not an ongoing metric), skipping it for a filing whose extraction already failed. `src/capitol_lake/stages/extract.py`'s private `_transaction_row` helper is renamed `transaction_row` (public), since the eval runner needs it to shape a predicted row the same way the silver Parquet write does, without duplicating that mapping. `eval/README.md` documents the sampling method, gold record format, scored-field rationale, averaging method, and the current run's findings (including why the scanned-column scores in this environment are an artifact of a missing `tesseract` binary, not real accuracy, and should be re-run somewhere it's installed).
- `src/capitol_lake/stages/ticker_resolve.py`: ticker resolution cascade (#39) — `resolve_ticker` fills a stock/ETF `Transaction`'s still-null `ticker` (the form's own printed symbol already handles the common case) by asset name, gated to `TICKER_ASSET_TYPES` (stock/ETF only; every other `asset_type` returns `None` without even calling OpenFIGI). OpenFIGI's free-text search (`search_openfigi`, injected) is tried first and its top-1 candidate accepted only on an exact/near-exact name match (`SequenceMatcher` ratio over a corp-suffix-stripped normalization, so "Amgen Inc." and "AMGEN INC" match but a same-shaped, different company never does just for ranking first); otherwise EDGAR's full `company_tickers.json` listing (`edgar_companies`, fetched once by the caller, not queried per line) is checked only to *confirm* one of OpenFIGI's own candidate tickers by an independent near-exact name match, never to introduce a ticker OpenFIGI didn't propose. No confident match at either stage yields `None`, never a best-effort guess. `parse_openfigi_search_response`/`parse_edgar_company_tickers` parse each API's raw JSON (an OpenFIGI error/empty response yields no candidates rather than raising). Wired into `extract_house_filing` (`stages/extract.py`) via an optional `resolve_ticker(asset_description, asset_type)` callable, called only for a transaction row whose `ticker` is still null and whose `asset_type` is stock/ETF — omitting it (the default, used by every existing test) performs no resolution at all. `handlers/extract_handler.py` wires it to real HTTP (stdlib `urllib`): OpenFIGI's `/v3/search` per unresolved row, EDGAR's `company_tickers.json` fetched once per invocation and reused across every row. Tests exercise the full decision table (gating, exact/near-exact top-1 acceptance, rejection of a merely-first-ranked non-match, EDGAR confirming a lower-confidence OpenFIGI candidate, EDGAR never introducing a ticker of its own, no-match-at-any-stage) entirely against canned/injected responses, no live network call.
- `src/capitol_lake/stages/extract.py`: extract stage — `extract_house_filing` parses `chamber`/`year`/`doc_id` from a bronze key, routes to `extract_digital` or `extract_scanned` via `route_doc_id` with no manual classification, and serializes the resulting `Filing`/`Transaction` rows into two Hive-partitioned Parquet part files (`filings`, `transactions`), one part per `doc_id` at `silver_key`'s layout (ADR 0008). Every transaction row is kept regardless of `asset_type`, with `asset_type` and the original `asset_description` always present in the output schema; the stage only routes and serializes, it never filters. Like the extractors underneath it, the pure function raises `DocIdMismatchError` rather than silently writing a row whose own `doc_id` disagrees with the bronze key's (the digital extractor reads `doc_id` from the PDF's own footer, independently of the key it was stored under) and never touches S3 itself — it returns each part file's key and bytes, and `handlers/extract_handler.py` (thin, `boto3`-backed) performs the actual read-from-bronze/write-to-silver. `pyarrow` is added as a dependency. `extract_handler.py` was manually exercised once against a local MinIO (a real digital House PTR fixture, through the handler, landed as a queryable Parquet row at the documented silver key), consistent with this repo's handlers staying untested by convention; that run isn't captured as a repeatable test. Tests reuse the same real fixtures as `test_digital_extract.py`/`test_scanned_extract.py`, round-tripping the returned Parquet bytes with `pyarrow` rather than just checking they're non-empty; the scanned-routing test path depends on a local `tesseract` binary, same as `test_scanned_extract.py`, and doesn't run in this sandbox (no `sudo`), but is exercised the same way test_scanned_extract.py already is. No `docker/extract.Dockerfile`/compose service yet: `dnf install tesseract` isn't available on the AWS Lambda Python 3.12 base image's default repos, so packaging Tesseract into this stage's container image needs a static binary or an EPEL-equivalent setup, deferred as a separate follow-up rather than solved here.
- `src/capitol_lake/stages/scanned_extract.py`: scanned House PDF extractor (ADR 0002, addendum #37). `extract_scanned` OCRs a scanned PTR (no text layer) with `pytesseract`/`pypdfium2` into a silver `Filing` and its `Transaction` rows. The paper form's mediabox is portrait but its content is landscape; the correcting rotation is decided once from page 1 (whichever of +/-90 degrees OCRs more of the form's own header words) and reused for the whole filing. Filer name and the Legislative Resource Center's date-received stamp OCR reliably from the full page; a filing where neither can be read raises rather than guessing. The transaction table's `transaction_type` and dollar-amount columns turned out to be hand/typed checkbox grids on every sampled scanned PTR (not typed text as ADR 0002 assumed for the amount) — full-page OCR of a checkbox is noise, not a value, so both are always null at low confidence, extending ADR 0002's own reasoning; `Transaction.value_range` and `transaction_type` became nullable to allow it. Asset name and the two transaction dates are typed/handwritten text, not checkboxes, and are recovered by isolating the asset-name and date-of-transaction columns as fixed fractions of the page (calibrated against sampled real scanned PTRs, coarser and cheaper than the zonal OCR ADR 0002 declined, since drifting a few percent only adds noise rather than changing which checkbox a value means) and stripping table grid lines before OCR, since a border touching a digit merges into an unrecognizable glyph. A row whose recovered text doesn't look like a plausible asset name is dropped rather than kept as a wrong or empty transaction, so scanned recall is honestly partial and template-dependent — some real filings extract every transaction, a heavily degraded scan may extract none, with the `Filing` row still valid. `pytesseract`, `pypdfium2`, and `numpy` are added as dependencies; CI installs the `tesseract-ocr` system package. Tests run on two real scanned House PTR PDFs in `tests/fixtures/`: one extracts fully, the other documents the honest-failure path (unreadable filer name/stamp raises instead of guessing). No Lambda handler yet, same as the digital extractor (#18).
- `src/capitol_lake/stages/digital_extract.py`: digital House PDF extractor (ADR 0003). `extract_digital` reads a text-layer PTR with `pypdf` into a silver `Filing` and its `Transaction` rows. It rebuilds visual lines from pypdf's positioned text and splits the table into rows by vertical gap, so a wrapped `Comments:` value or a row split by a page break stays on its own Transaction. Each row is anchored on its `<type> <date> <date> <$range>` transaction line. Its `Filing Status:`/`Subholding Of:`/`Description:` lines (plus the unstored `Location:`/`Comments:`) are label-validated with whitespace stripped and NUL as a wildcard, which is how pypdf 6 garbles bold labels. A label absent from its row is a confident null, never a positional guess; `LOW_CONFIDENCE` is kept for what is present but unreadable, and a row's `confidence` is its lowest field confidence. The 2020-2022 form template (mixed-case small-caps labels, capitals mapped to lowercase, checkbox glyph text) is handled too; a scan of 157 filings from 2020-2025 (2,504 rows) found no misattributed line. `pypdf` is added as a dependency. Tests run on nine real House PTR PDFs (2021, 2025) in `tests/fixtures/`, including a notification date printed before its transaction date (kept as printed), a mid-table missing `Subholding Of:`, page-break splits and wrapped comments. No Lambda handler yet; that wiring belongs to the orchestration work (#18).
- `src/capitol_lake/stages/senate_collect.py`: Senate collector — `route_filing_kind`/`parse_senate_index` route and filter a captured eFD search response (`POST /search/report/data/` JSON body, format confirmed against a real recorded response) to `/ptr/` entries with no network call, deriving each entry's year from its row (`/paper/` and every other report kind skipped, never fetched), and `collect_senate` orchestrates the rate-limited (~1 req/s) fetch-and-`bronze_write` loop over injected network/S3 callables, keyed by the filing's Senate eFD UUID (amendments as their own separate UUID); `handlers/senate_collect_handler.py` wires it to real `urllib`/`boto3` clients, with a `docker/senate_collect.Dockerfile` and `senate-collect-stage` compose service. Not scheduled (#18): the Senate eFD search UI is Akamai bot-protected — confirmed live to also block individual `/ptr/` pages and cookie-reuse via a plain HTTP client, only a real browser engine clears it (#23) — so the stage is invoked manually (or via a local headless-browser step) with a captured search response rather than discovering the index itself. `tests/fixtures/senate_ptr_sample.html` is a real fetched `/ptr/` filing page (captured the same session, via a headless-Chromium session that cleared the Akamai check), round-tripped byte-for-byte through `bronze_write` in a test — not just synthetic bytes.
- `src/capitol_lake/stages/house_collect.py`: House collector — `route_doc_id` classifies a doc id as digital (`20…`) or scanned (`82…`/`91…`) with no network call, `parse_house_index` parses the annual index ZIP into routed entries, and `collect_house` orchestrates the rate-limited (~1 req/s) fetch-and-`bronze_write` loop against fully injected network/S3 callables; `handlers/house_collect_handler.py` wires it to real `urllib`/`boto3` clients, with a `docker/house_collect.Dockerfile` and `house-collect-stage` compose service.
- `src/capitol_lake/schema.py`: silver-layer `Filing` and `Transaction` models — canonical `Owner`/`TransactionType` enums with raw-text fields, `(min, max)` `ValueRange`, an invariant-enforced `disclosure_lag`, a `ticker` slot for future resolution, and row-level `confidence`/`Provenance`.
- ADR 0010: FinOps decision — AWS Budget filtered by the `Project=capitol-lake` cost allocation tag, alert thresholds, and Terraform tagging scheme.
- `src/capitol_lake/` skeleton with the pure-function-plus-handler stage convention, a stub stage/handler pair, and shared bronze/silver S3 key-layout helpers.
- Local MinIO + Lambda Runtime Interface Emulator scaffold (`docker-compose.yml`, `docker/lambda.Dockerfile`) mirroring the intended S3 key layout, with conventions documented in `docs/local-dev.md`.
- `src/capitol_lake/stages/bronze_write.py`: chamber-agnostic bronze contract — a pure, hash-gated idempotent write decision (no-op on matching sha256, versioned `<doc_id>.<sha256[:8]>.<ext>` key on a different hash, original key never overwritten) plus the sidecar `.meta.json` payload; `bronze_versioned_key`/`bronze_meta_key` key helpers.

### Fixed

- Senate eFD Akamai check: the `403` every automated run hit (#67's own
  hand test, #68's first RIE run) traced to a browser fingerprint signal,
  not network/Lambda-egress-IP origin as previously concluded — the default
  headless Chromium UA's `HeadlessChrome` substring (a four-way diagnostic
  ruled out `navigator.webdriver` as the operative signal).
  `capitol_lake.browser.senate_efd_session`'s new
  `de_headless_user_agent(browser)` helper (derived from `browser.version`,
  re-exported from `probes.senate_akamai_probe`) is now passed to
  `browser.new_page()` in both `run_senate_efd_session` and
  `probes.senate_akamai_probe.run_probe`. Confirmed by hand from the same
  network/sandbox that previously 403'd: a real RIE invocation now writes a
  real bronze object, verified in MinIO — see
  `docs/research/senate-efd-session-hand-test.md`'s Update section and
  `docs/research/senate-collect-automated-handler-rie-test.md`'s Update
  section. No real AWS Lambda deploy is needed to clear the check after all.
- `src/capitol_lake/stages/digital_extract.py`: `parse_value_range` now
  accepts a bare `$X[.XX]` literal amount (e.g. `$9.00`), treating it as
  `ValueRange(X, X)`, instead of returning `None` and failing the whole
  filing's extraction with `unreadable amount`. Two real 2023 House PTRs
  sampled while building the #40 gold set print this shape for a
  small-value line under the $1,000 bracket-reporting threshold: `20022260`
  (Pelosi, `$9.00`) and `20023819` (Sessions, `$569.25` and `$493.91`), both
  now added as `tests/fixtures/house_digital_*.pdf` regression fixtures.
  (#57)

### Changed

- `src/capitol_lake/stages/_house_form.py`: House owner-code and asset-type/ticker regexes and lookup tables (`OWNER_RE`, `OWNERS`, `ASSET_TYPE_CODE_RE`, `ASSET_TYPES`, `PRINTED_SYMBOL_RE`), shared by `digital_extract.py` and `scanned_extract.py` instead of duplicated between them, with no behavior change.
- `src/capitol_lake/schema.py`: `Transaction.transaction_type` and `Transaction.value_range` are now nullable — both are hand/typed checkbox grids on a scanned PTR, unreadable from full-page OCR for the same reason ADR 0002 already declined zonal OCR for `transaction_type` (see its #37 addendum); a digital filing's typed text still yields both, so this is additive there.
- `src/capitol_lake/schema.py`: `Transaction` gains optional `notification_date`, `filing_status`, `sub_owner` (the form's `Subholding Of:`) and `description` fields, plus a per-field `field_confidence` map (excluded from the hash): a null at full confidence means the source has no such line, a low one that it couldn't be read. `ValueRange.max` is nullable, null for an open-ended `Over $X` bracket, instead of an infinity that breaks JSON and sums.
- Project configured from the harness template: name, code standards, agent skills docs.
