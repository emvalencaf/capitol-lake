# infra

Terraform for capitol-lake's AWS cloud lift (ADR-0009, ADR-0011, ADR-0012).
Single environment, no dev/staging (ADR-0009's scoping decision).

## Layout

- `bootstrap/` — one-time, local-state module that creates the S3 bucket the
  main stack's own backend depends on, plus the GitHub Actions OIDC provider
  and IAM role `.github/workflows/infra-cicd.yml` assumes (#46). Run this
  first, by hand.
- `modules/storage` — bronze/silver S3 buckets.
- `modules/pipeline` — ECR repositories, IAM roles, SSM secret parameters,
  and the four Lambda stages (`house-collect`, `senate-collect`,
  `senate-collect-automated`, `extract`), each via `modules/lambda-stage`.
- `modules/scheduling` — House's and the automated Senate collector's
  EventBridge schedules, plus the manual Senate path's S3-event trigger into
  `extract`.
- `modules/finops` — the tag-filtered AWS Budget, House's dead-man's-switch
  staleness alarm, and the automated Senate collector's dedicated Errors
  alarm (ADR-0010, #69), all alerting through one SNS topic.
- `main.tf` / `variables.tf` / `outputs.tf` / `providers.tf` / `versions.tf`
  at this level — the root module composing the above.

## Production deploy walkthrough (#46, #79)

This is the full path from a fresh AWS account to a running `terraform apply`
on `master`, gated by GitHub's required-reviewer approval. Steps 1–2 are
one-time, by hand; step 3 is what happens automatically on every PR and merge
once they're done.

### 1. Bootstrap (local state, run once by hand)

```bash
cd infra/bootstrap
terraform init
terraform apply
terraform output state_bucket_name       # feed into backend.hcl below
terraform output github_actions_role_arn # feed into the AWS_ROLE_ARN repo variable below
```

This creates the S3 state bucket, the GitHub Actions OIDC provider, and the
`capitol-lake-github-actions-terraform` IAM role that CI assumes — see
`infra/bootstrap/oidc.tf` for the trust policy. It also creates no long-lived
AWS access keys: the role is only assumable via `sts:AssumeRoleWithWebIdentity`
from GitHub's OIDC token, scoped by `sub` to either a pull request touching
this repo or a run through the `github_environment`-named GitHub Environment
(default `production`).

Point the main stack's backend at the new bucket:

```bash
cd ..
cp backend.hcl.example backend.hcl   # gitignored; fill in bucket/region
terraform init -backend-config=backend.hcl
terraform plan -var="finops_alert_email=you@example.com"
```

A plain `terraform apply` fails on a fresh account: every stage's Lambda is
`package_type = "Image"` pointing at `<its ECR repo>:latest`
(`modules/pipeline/main.tf`), but that repo doesn't exist with an image in it
until the same apply creates it — Terraform errors with "Provide a valid
source image." `scripts/deploy-infra.sh up` automates the fix (apply the ECR
repos only, build and push each stage's image from `docker/*.Dockerfile`,
then apply the rest of the stack), the same three-step dance
`scripts/deploy-senate-akamai-probe.sh` already does for the standalone probe
Lambda:

```bash
cd ..
FINOPS_ALERT_EMAIL=you@example.com scripts/deploy-infra.sh up
```

Populating the SSM secret parameters with real values (LLM fallback /
ticker resolution API keys) is a separate, manual post-apply step — see
"Notes" below. From here on, `apply` runs through CI (step 3), not by hand.

### 2. One-time GitHub setup

- Create a GitHub Environment named `production` (repo Settings >
  Environments) with a required reviewer added under **Deployment
  protection rules**. This Environment is what actually gates `apply` — the
  workflow file just references it by name. Its name must match
  `var.github_environment` in `infra/bootstrap` (default `production`).
- Set these as repository **variables** (Settings > Secrets and variables >
  Actions > Variables tab — not Secrets; none of these grant AWS access on
  their own without the OIDC trust condition):
  - `AWS_ROLE_ARN` — `infra/bootstrap`'s `github_actions_role_arn` output.
  - `TF_STATE_BUCKET` — `infra/bootstrap`'s `state_bucket_name` output.
  - `FINOPS_ALERT_EMAIL` — same value as `var.finops_alert_email` above; this
    is the address subscribed to the budget-alert/staleness SNS topic
    (`infra/modules/finops`).

### 3. What CI does (`.github/workflows/infra-cicd.yml`)

- **Pull requests touching `infra/**`, into `development` or `master`** run
  the `plan` job: OIDC auth via `AWS_ROLE_ARN`, `terraform init` against the
  `TF_STATE_BUCKET` backend, then `terraform plan`. No Environment gate —
  read-only against the real state, output visible in the PR's Actions run
  log (Terraform posts no PR comment; there's no comment-posting step in the
  workflow).
- **Push to `master`** (i.e. the `development` → `master` release PR from
  `CONTRIBUTING.md` landing) runs the `apply` job through the `production`
  Environment. The job starts but **waits** at the Environment gate until a
  required reviewer approves it:
  1. Open the workflow run under the repo's **Actions** tab.
  2. The `apply` job shows as pending with a **Review deployments** button.
  3. A user listed as a required reviewer on the `production` Environment
     clicks it, selects `production`, and approves (or rejects) the run.
  4. Once approved, `terraform apply` runs with the same OIDC-assumed role
     and backend as `plan`.

  Nothing else in the workflow file enforces this pause — deleting or
  misconfiguring the `production` Environment's protection rule removes the
  gate entirely, so that Environment's settings are the actual control, not
  the YAML.

## Notes

- **Fresh-account concurrency quota.** Each of the 4 stage Lambdas reserves
  `var.stage_reserved_concurrency` (default 5, ADR reasoning in
  `variables.tf`) — 20 total. AWS always keeps at least 10 units unreserved
  account-wide, so if the account's Lambda concurrent-executions quota is
  below ~30 (common on a brand-new account before it's requested an
  increase), `terraform apply` fails on every stage with "decreases
  account's UnreservedConcurrentExecution below its minimum value of [10]".
  Check the quota with `aws lambda get-account-settings --query
  AccountLimit`; either request a Service Quotas increase for "Concurrent
  executions", or unblock the first apply with
  `-var="stage_reserved_concurrency=-1"` (or
  `TF_VAR_stage_reserved_concurrency=-1`, which `scripts/deploy-infra.sh`
  also picks up) until the quota is raised.
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
