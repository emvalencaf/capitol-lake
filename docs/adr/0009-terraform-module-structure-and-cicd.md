# Terraform module structure, state, and CI/CD for the cloud lift

The cloud lift (#18 orchestration, #19 storage) needs an IaC layout that a
solo developer can stand up and maintain on a free-tier AWS budget, in a repo
that goes public in Phase 3. We chose a module-per-concern layout, S3-only
remote state, GitHub Actions for `plan`/`apply`, and OIDC for AWS auth.

## Decisions

- **State backend**: S3 with native S3 locking (`use_lockfile = true`,
  requires Terraform >= 1.10) instead of S3 + DynamoDB. Same durability and
  locking guarantees, one fewer resource to provision, tag and explain.
  `required_version = ">= 1.10"` is pinned in `versions.tf` to guarantee this
  feature is available wherever `terraform` runs (local or CI).
- **Backend bootstrap**: `infra/bootstrap/` is a separate, minimal root
  module (its own local state) that provisions only the state bucket. Run
  once by hand, before the main stack can use S3 as its backend. Kept in the
  repo so "how do I stand this up from zero" is answerable from the repo
  itself, not tribal knowledge.
- **Module boundaries**: one module per concern —
  `infra/modules/storage`, `infra/modules/pipeline`, `infra/modules/lambda-stage`,
  `infra/modules/scheduling` — composed by a root module. `lambda-stage` is
  instantiated four times (collect, extract, ticker/LLM-fallback,
  silver-write per #18), each with its own DLQ and IAM role.
- **Environments**: single environment only (no dev/staging). This is a
  scoping decision, not an omission: the project is a portfolio sample with
  one free-tier AWS account and no requirement in this map's Destination for
  a second environment. Revisit as a fresh decision if that ever changes.
- **Secrets**: Lambda runtime credentials (LLM provider keys per #14) are
  provisioned as SSM Parameter Store `SecureString` parameters — Terraform
  creates the (empty) parameter, a human populates the value post-apply, and
  Lambda reads it via IAM at runtime. AWS Secrets Manager would be the ideal
  fit for this (built-in rotation, resource-based access), but has no
  free-tier and was rejected on cost grounds alone.
- **Shared tags**: a `common_tags` map variable is defined once in the root
  module and passed into every child module, which merges it with its own
  specific tags. Gives #21 (FinOps cost-allocation tags) a single place to
  define the tagging convention instead of hunting tags across modules.
- **Directory layout**: `infra/` at the repo root — `infra/bootstrap/`,
  `infra/modules/...`, and the main root module directly under `infra/`.
- **Provider/version pinning**: `required_version` and `required_providers`
  (`~> 5.0` for the AWS provider) declared in `versions.tf`, with
  `.terraform.lock.hcl` committed. Two different machines (local dev,
  GitHub Actions) run `apply`, so the resolved provider version must be
  identical on both.
- **Apply mechanism**: GitHub Actions, not local. `terraform plan` runs on
  every pull request touching `infra/**`; `terraform apply` runs on merge to
  `master` (the protected, stable branch per CONTRIBUTING.md), gated behind
  a GitHub Environment with a required reviewer — a deliberate self-check
  before infra changes hit the real account, distinct from ordinary code-PR
  review.
- **AWS authentication from CI**: OIDC federation (GitHub's OIDC provider
  trusted by an IAM role, assumed per run) instead of long-lived access keys
  stored as repo secrets. Removes the "AWS key leaked from a public repo"
  risk category entirely, which matters once the repo goes public in
  Phase 3.
- **Workflow trigger scope**: the Actions workflow is path-filtered to
  `infra/**`, so PRs that only touch Python/notebook code don't trigger a
  Terraform plan run.

## Considered options

- **S3 + DynamoDB state locking**: rejected in favor of S3 native locking —
  functionally equivalent, but adds a resource with no benefit once
  Terraform >= 1.10 is pinned anyway.
- **Single flat root module** or **module per AWS service**: rejected in
  favor of module-per-concern; flat matches the current size but doesn't
  scale with the tagging/reuse needs of four near-identical Lambdas, and
  per-service modules over-fragment pieces (bucket, SQS chain) that exist
  once.
- **Workspace/dir-per-environment**: rejected — no second environment is in
  scope for this map.
- **Long-lived AWS access keys in GitHub secrets**: rejected in favor of
  OIDC, given the repo's public Phase 3 future.
- **Local-only `terraform apply`**: rejected once GitHub Actions was chosen
  as the apply mechanism, since remote CI runs need shared remote state
  regardless.
