---
type: Decision
title: "ADR 0009: Terraform module structure, state, and CI/CD for the cloud lift"
description: Module-per-concern Terraform layout, S3-only remote state, GitHub Actions plan/apply, and OIDC for AWS auth.
resource: ../../docs/adr/0009-terraform-module-structure-and-cicd.md
tags: [decision, terraform, cicd]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0009-terraform-module-structure-and-cicd.md
    title: "ADR 0009"
---

# Overview

The cloud lift needs an IaC layout a solo developer can run on a free-tier
AWS budget, in a repo that goes public in Phase 3. Decided: S3 remote state
with native locking (no DynamoDB), a separate `infra/bootstrap/` root module
to stand up the state bucket by hand, one module per concern (`storage`,
`pipeline`, `lambda-stage` instantiated per stage, `scheduling`), a single
environment, SSM `SecureString` parameters for runtime secrets (Secrets
Manager rejected on cost), a shared `common_tags` variable, and GitHub
Actions running `plan` on PRs and `apply` on merge to `master` via
OIDC-federated IAM rather than long-lived access keys.[^adr]

Refined by [ADR 0011](0011-extract-stage-alt-base-image-and-lambda-count.md)
(actual Lambda count) and [ADR 0012](0012-terraform-root-stack-wiring.md)
(root-stack wiring).

[^adr]: ADR 0009
