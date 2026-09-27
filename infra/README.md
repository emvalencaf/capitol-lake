# infra

Terraform for capitol-lake's AWS cloud lift (ADR-0009, ADR-0011, ADR-0012).
Single environment, no dev/staging (ADR-0009's scoping decision).

## Layout

- `bootstrap/` — one-time, local-state module that creates the S3 bucket the
  main stack's own backend depends on, plus the GitHub Actions OIDC provider
  and IAM role `.github/workflows/infra-cicd.yml` assumes (#46). Run this
  first, by hand.
- `modules/storage` — the single project S3 bucket; bronze/silver are key
  prefixes inside it, not separate buckets.
- `modules/pipeline` — ECR repositories, IAM roles, SSM secret parameters,
  and the four Lambda stages (`house-collect`, `senate-collect`,
  `senate-collect-automated`, `extract`), each via `modules/lambda-stage`.
- `modules/scheduling` — House's and the automated Senate collector's
  EventBridge schedules. Every collector (House, and both Senate paths)
  enqueues its own writes onto extract's SQS queue directly from its handler
  (ADR-0016), so there's no bridging infra for that here.
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
terraform output github_actions_role_arn # feed into the AWS_ROLE_ARN repo secret below
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
then apply the rest of the stack), the same three-step dance the now-retired
senate-akamai-probe standalone Lambda (#70) used to use:

```bash
cd ..
FINOPS_ALERT_EMAIL=you@example.com scripts/deploy-infra.sh up
```

Populating the SSM secret parameters with real values (LLM fallback /
ticker resolution API keys) is a separate, manual post-apply step — see
"Notes" below. From here on, `apply` runs through CI (step 3), not by hand.

### 2. One-time GitHub setup

`scripts/setup-github-env.sh up` automates this whole step against the
GitHub API via `gh` (must be authenticated: `gh auth status`):

```bash
cd ..
GH_REVIEWER=your-github-username \
FINOPS_ALERT_EMAIL=you@example.com \
  scripts/setup-github-env.sh up
```

It reads `infra/bootstrap`'s `github_actions_role_arn` / `state_bucket_name`
outputs, creates (or updates) the `production` GitHub Environment with
`GH_REVIEWER` (comma-separated for more than one) as its required reviewer,
and sets the three secrets below. Run `scripts/setup-github-env.sh down` to
remove them again — add `--purge-history` to also delete every
`infra-cicd.yml` workflow run and every deployment recorded against the
Environment (irreversible; asks for a second confirmation). See the script's
own header comment for every flag and env var.

GitHub's required-reviewer protection rule needs GitHub Team/Enterprise on
a **private** repo (public repos get it on any plan, ADR-0009's Phase 3
plan) — if `up` 422s on that, either upgrade the plan, make the repo
public, or pass `--no-reviewer` to create the Environment without the gate
for now.

Equivalently, by hand:

- Create a GitHub Environment named `production` (repo Settings >
  Environments) with a required reviewer added under **Deployment
  protection rules**. This Environment is what actually gates `apply` — the
  workflow file just references it by name. Its name must match
  `var.github_environment` in `infra/bootstrap` (default `production`).
- Set these as repository **secrets** (Settings > Secrets and variables >
  Actions > Secrets tab — not Variables; none of these grant AWS access on
  their own without the OIDC trust condition, but they're kept as secrets
  rather than plaintext variables so GitHub masks them in Actions logs —
  worth doing given this repo's public Phase 3 future, ADR-0009):
  - `AWS_ROLE_ARN` — `infra/bootstrap`'s `github_actions_role_arn` output.
  - `TF_STATE_BUCKET` — `infra/bootstrap`'s `state_bucket_name` output.
  - `FINOPS_ALERT_EMAIL` — same value as `var.finops_alert_email` above; this
    is the address subscribed to the budget-alert/staleness SNS topic
    (`infra/modules/finops`).

### 3. What CI does (`.github/workflows/infra-cicd.yml`)

- **Pull requests touching `infra/**`, into `development` or `master`** run
  the `plan` job: OIDC auth via the `AWS_ROLE_ARN` secret, `terraform init`
  against the `TF_STATE_BUCKET` secret's backend, then `terraform plan`. No
  Environment gate —
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

- **Stage concurrency defaults unreserved.** `var.stage_reserved_concurrency`
  defaults to `-1` (no reservation; every stage shares the account's general
  concurrency pool), matching this project's demonstrative scope. #43's
  original reasoning for reserving concurrency per stage (5 apiece, isolate
  per-filing failures and stay polite to downstream free-tier APIs) still
  applies if this ever carries real production traffic — set
  `stage_reserved_concurrency = 5` (an `infra/terraform.tfvars`, gitignored,
  is the easiest way) if so. Reserving concurrency has a fresh-account
  gotcha worth knowing either way: AWS always keeps at least 10 units
  unreserved account-wide, so a new account's default Lambda
  concurrent-executions quota (often well under the ~30 units 4 stages at 5
  each would need) makes `terraform apply` fail on every stage with
  "decreases account's UnreservedConcurrentExecution below its minimum value
  of [10]" until a Service Quotas increase is requested
  (`aws lambda get-account-settings --query AccountLimit` shows the current
  quota).
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
