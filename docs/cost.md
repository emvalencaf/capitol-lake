# AWS cost estimate

Part of #75. This page estimates the AWS bill for the pipeline described in
[architecture.md](architecture.md), built from a real
[AWS Pricing Calculator](https://calculator.aws) estimate:

**[View the shareable estimate](https://calculator.aws/#/estimate?id=7267b60b4a470b5e755d339130acde8a68803c6f)**
("capitol-lake AWS cost estimate (issue #77)", US East (N. Virginia), dated
2026-09-26 — the calculator's own read-only snapshot of that date's pricing).

## Volume assumptions

- **House: ~451–515 PTRs/year**, cited to
  [ADR 0008](adr/0008-silver-storage-stays-parquet-part-per-doc-id.md) (itself
  citing issue #3).
- **Senate: ~55–60 PTRs/year, a derived estimate.** `eval/README.md`'s Senate
  gold-set sampling found 661 combined `/ptr/`+`/paper/` matches over the
  `01/01/2022`–`09/26/2026` (~4.75-year) eFD search window, of which the first
  100 rows were 40% `/ptr/` (the rest `/paper/`, out of scope). Applying that
  ~40% fraction to the full 661: `661 × 0.40 ≈ 264` `/ptr/` filings over 4.75
  years ≈ **56/year** — consistent with the issue's ~55–60 range. This is a
  ratio applied across a search window, not a direct per-year count, so it's
  labeled an estimate rather than cited as a measurement.
- **Total: ~506–575 filings/year** (midpoint ~540) feeding the shared
  extract → ticker/LLM-fallback → silver-write stage.

## What's priced, and why

Both collectors run on their own daily `rate(1 day)` EventBridge schedule
(`infra/modules/scheduling`) — 365 invocations/year each, regardless of
whether a new filing exists that day. That's the **fixed scheduling cost**.
Every filing that reaches Bronze then triggers exactly one `extract` Lambda
invocation (ticker resolution, LLM fallback, and the Silver write all happen
inside that one handler — see architecture.md's implementation note) — that's
the **per-filing processing cost**, scaling with the volume above rather than
with the calendar.

Lambda memory/timeout figures come straight from `infra/modules/pipeline/main.tf`
and `infra/modules/lambda-stage/variables.tf` (house-collect: 512MB default;
senate-collect-automated: 2048MB, sized for a real headless-Chromium eFD
session; extract: 1024MB). **Average invocation duration is not measured** —
no CloudWatch metrics exist yet for a pipeline that hasn't been deployed — so
each duration below is an explicit assumption, not an observed value:

| Stage | Trigger | Memory | Assumed avg. duration | Assumed monthly volume |
|---|---|---|---|---|
| `house-collect` | EventBridge, daily | 512 MB | ~15s (most days: list + no new filing) | 31 invocations |
| `senate-collect-automated` | EventBridge, daily | 2048 MB | ~60s (worst case is the 900s timeout ceiling; most days finish well under it, per the module's own comment) | 31 invocations |
| `extract` | SQS (House and Senate, ADR-0016) | 1024 MB | ~10s | 47 invocations (~540/yr ÷ 12) |

The `extract` row's volume is a Lambda-invocation count, not a "both chambers
are fully processed" claim: Senate's collectors already enqueue onto the
same SQS queue House does (`infra/modules/pipeline`), so the Lambda genuinely
runs once per Senate filing too — but architecture.md's implementation note
is explicit that the handler doesn't yet dispatch a Senate bronze key to the
Senate extractor, so today those invocations do real House work and no-op
(or error) on Senate input. The invocation-count math above holds regardless;
the per-filing *processing* cost will change once that dispatch wiring lands.

**EventBridge itself is not priced.** `infra/modules/scheduling` uses classic
`aws_cloudwatch_event_rule` targets on the *default* event bus — AWS does not
bill default-bus rules that target a Lambda function; only custom event buses
and `PutEvents` calls are billed. The `$1/million invocations` EventBridge
Scheduler price often quoted elsewhere applies to a different, newer service
this repo doesn't use.

S3 storage is estimated from one year of accumulated Bronze (raw PDFs/HTML)
+ Silver (Parquet) at current volume — roughly 300MB/year of raw filings plus
a few MB of Parquet, rounded up to 1 GB/month for the calculator entry, an
explicit assumption. SQS is priced at ~3 requests (Send + Receive + Delete)
per House filing, the only chamber that goes through `extract`'s queue
(Senate's dispatch to `extract` isn't wired yet — see architecture.md).

**Excluded by deliberate choice:** ECR image storage. At four small container
images this is negligible next to the numbers above, and — also by deliberate
choice, given this project's demonstrative scope — no ECR lifecycle/retention
policy is configured, so old image versions accumulate rather than being
pruned automatically.

## Cost table

Costs below are **gross, on-demand** (no free-tier discount applied) so each
stage is comparable — this is also the AWS Pricing Calculator's default
"Without Free Tier" framing for Lambda. The linked estimate itself uses
"Include Free Tier" (the realistic default), which is why its total reads far
lower — see the note below the table.

| | Stage | Gross cost / year |
|---|---|---:|
| **Fixed scheduling** | `house-collect` (Lambda compute + requests) | $0.047 |
| | `senate-collect-automated` (Lambda compute + requests) | $0.744 |
| | **Fixed subtotal** | **$0.79** |
| **Per-filing processing** | `extract` (Lambda compute + requests) + SQS | $0.095 |
| | S3 storage (Bronze + Silver, PUT/GET requests) | $0.285 |
| | **Per-filing subtotal** | **$0.38** |
| | **Total (gross, no free tier)** | **~$1.17/year** |

**Realized net cost, at this actual volume: $0.24/year** (the linked
calculator estimate's own total). Lambda's free tier is 1M requests +
400,000 GB-seconds/month, *permanently*, not a 12-month trial — and this
pipeline's real projected usage (≈108 requests/month, ≈4,344 GB-seconds/month
across all three functions) sits entirely inside it, as does SQS's 1M
free requests/month. The only line item free tier doesn't erase is S3
storage, which is only free for a new account's first 12 months. At this
project's scale, essentially the entire AWS bill *is* S3 storage.

## Cost by stage

![Estimated AWS cost by stage: a horizontal bar chart showing gross annual
cost for senate-collect-automated ($0.744), S3 storage ($0.285), extract
($0.095), and house-collect ($0.047), with a note that net cost after AWS's
Lambda/SQS free tier is $0.24/year](diagrams/assets/cost-by-stage.svg)

## Caveats

- Every duration/size figure marked "assumed" above is a placeholder until
  the pipeline is deployed and CloudWatch has real invocation metrics to
  replace it with. Re-run this estimate once real data exists.
- This page prices AWS infrastructure only. It excludes the LLM fallback
  stage's own third-party API usage (Gemini/Groq, per `infra/modules/pipeline`),
  which is billed outside AWS and out of this issue's scope.
- The Senate volume figure is derived (a ratio applied to a combined count),
  not measured directly — see "Volume assumptions" above.
