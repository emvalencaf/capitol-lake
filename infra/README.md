# infra

Terraform for capitol-lake's AWS cloud lift (ADR-0009, ADR-0011, ADR-0012).
Single environment, no dev/staging (ADR-0009's scoping decision).

## Layout

- `bootstrap/` — one-time, local-state module that creates the S3 bucket the
  main stack's own backend depends on. Run this first, by hand.
- `modules/storage` — bronze/silver S3 buckets.
- `modules/pipeline` — ECR repositories, IAM roles, SSM secret parameters,
  and the three Lambda stages (`house-collect`, `senate-collect`, `extract`),
  each via `modules/lambda-stage`.
- `modules/scheduling` — House's EventBridge schedule and Senate's S3-event
  trigger into `extract`.
- `modules/finops` — the tag-filtered AWS Budget and dead-man's-switch
  staleness alarm (ADR-0010), both alerting through one SNS topic.
- `main.tf` / `variables.tf` / `outputs.tf` / `providers.tf` / `versions.tf`
  at this level — the root module composing the above.

## Standing it up from zero

```bash
# 1. Bootstrap the state bucket (local state, run once by hand).
cd infra/bootstrap
terraform init
terraform apply
terraform output state_bucket_name  # feed into backend.hcl below

# 2. Point the main stack's backend at that bucket.
cd ..
cp backend.hcl.example backend.hcl   # gitignored; fill in bucket/region
terraform init -backend-config=backend.hcl

# 3. Review the plan against a fresh account.
terraform plan -var="finops_alert_email=you@example.com"
```

`terraform apply` (building/pushing each stage's container image to its ECR
repository, and populating the SSM secret parameters with real values) is a
deployment step, out of scope for the infra work tracked here.

## Notes

- State locking is native S3 (`use_lockfile = true`, Terraform >= 1.10) — no
  DynamoDB table (ADR-0009).
- Secrets (LLM fallback / ticker resolution API keys) are SSM `SecureString`
  parameters, not Secrets Manager (ADR-0009) — Terraform creates them empty;
  populate the real value by hand post-apply.
- House's EventBridge schedule input carries a static filing year
  (`var.house_filing_year`), bumped by hand once a year (ADR-0012).
- `var.finops_alert_email` has no default and must be supplied (`-var` or a
  `.tfvars` file) — it's the email subscribed to the budget-alert/staleness
  SNS topic. AWS sends a confirmation email to it on first `apply`; the
  subscription stays pending until confirmed.
- The Budget only sees spend tagged `Project=capitol-lake` once that tag is
  activated as a cost allocation tag in the Billing Console — a manual,
  one-time step outside Terraform's reach (ADR-0010).
