# Wiring the Terraform root stack (#44): bucket naming, SSM secret handoff, S3-event scoping, schedule input

ADR-0009 settled the module boundaries (`storage`, `pipeline`, `lambda-stage`,
`scheduling`, plus `bootstrap`) and ADR-0011 settled the actual three-Lambda
topology, but `infra/modules/lambda-stage` wasn't yet wired into a deployable
root stack. #44 does that wiring; four decisions came up that weren't already
settled by either ADR.

## Decisions

- **Bucket naming**: bronze/silver bucket names are `${var.bucket_prefix}-bronze`/
  `-silver`, `bucket_prefix` defaulting to `capitol-lake`. S3 bucket names are
  globally unique across all AWS accounts, not just this one; a real `apply`
  against a fresh account may need to override `bucket_prefix` if the default
  is already taken elsewhere. Same reasoning for `ecr_repo_prefix` (ECR
  repository names are only account-unique, so this is mostly cosmetic
  consistency with the bucket naming).
- **SSM secret handoff to the extract Lambda**: `infra/modules/pipeline`
  provisions the three `SecureString` parameters ADR-0009 calls for
  (`/capitol-lake/openfigi-api-key`, `/capitol-lake/gemini-api-key`,
  `/capitol-lake/groq-api-key`) with a placeholder value and
  `lifecycle { ignore_changes = [value] }`, so a human populating the real
  value post-apply is never clobbered by the next `plan`/`apply`. Only the
  parameter *names* are passed to the extract Lambda as environment variables
  (`OPENFIGI_API_KEY_SSM_PARAM` etc.), not the values. `extract_handler.py`
  currently reads these secrets as plain environment variables
  (`OPENFIGI_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`) rather than fetching
  them from SSM at runtime — wiring the handler to actually call
  `ssm:GetParameter` is left as follow-up, since #44 is infra-only and
  changing handler behavior is out of scope here. The IAM permission
  (`ssm:GetParameter` scoped to those three parameter ARNs, on the extract
  role only) is provisioned now regardless, since granting it doesn't depend
  on the handler change.
- **S3-event scope for Senate**: the bronze bucket's `aws_s3_bucket_notification`
  (in `infra/modules/scheduling`) is filtered to `bronze/senate/` prefix and
  `.html` suffix, not every `ObjectCreated` event on the bucket. Without the
  prefix filter, a House bronze write would *also* trigger `extract` via S3
  event — on top of `house_collect_handler.py`'s own SQS enqueue — double-
  processing every House filing. The suffix filter excludes
  `bronze_write.py`'s `.meta.json` sidecar object, which is not a bronze
  filing `extract_handler.py` can parse.
- **House schedule input is a static year, not a computed one**: the
  EventBridge target's `input` is `{"year": var.house_filing_year}`, a plain
  number bumped by hand once a year, rather than something computed from
  `timestamp()` in Terraform. House PTRs are indexed by filing year
  (`house_collect.py`); a value derived from the current timestamp would
  make every `plan` show a spurious diff once the computed value drifted
  from what's actually deployed, for a value that only needs to change
  once/year anyway.

## Consequences

- `infra/modules/lambda-stage` gained a `function_name` output (previously
  only `function_arn`); `scheduling`'s `aws_lambda_permission` resources need
  the plain function name, not the ARN.
- Building/pushing each stage's container image, running `infra/bootstrap`
  by hand, and populating the SSM parameter values post-apply are all
  deployment steps, not Terraform config — out of scope for #44 (`terraform
  plan`, not `apply`, is the acceptance bar) and not automated here.
- `terraform plan` was verified against a fake AWS credential rather than a
  real fresh account (none available in this environment): `terraform
  validate` passes for the root module and `infra/bootstrap`, and a `plan`
  run gets past all resource/provider config parsing, only failing at the
  provider's own `sts:GetCallerIdentity` call once it reaches AWS — the
  furthest checkable without real credentials.

### Considered options

- **Computing the House schedule's year from `timestamp()`**: rejected —
  would make `plan` non-idempotent for a value that only needs a yearly
  human bump.
- **Unscoped S3 bucket notification (no prefix/suffix filter)**: rejected —
  double-processes every House filing, since House already chains to
  extract via SQS.
- **Wiring `extract_handler.py` to read secrets from SSM at runtime, as part
  of this ticket**: rejected — #44 is scoped to infra; changing handler
  behavior belongs to whichever ticket actually needs the LLM
  fallback/ticker-resolution secrets live in AWS (the local/MinIO dev path
  already works off plain env vars via `.env`).
