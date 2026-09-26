---
type: Decision
title: "ADR 0012: Wiring the Terraform root stack -- bucket naming, SSM handoff, S3-event scoping, schedule input"
description: Four wiring decisions -- bucket/ECR prefix naming, SSM parameter-name-only handoff, prefix/suffix-scoped Senate S3 event, and a hand-bumped House schedule year.
resource: ../../docs/adr/0012-terraform-root-stack-wiring.md
tags: [decision, terraform, wiring]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0012-terraform-root-stack-wiring.md
    title: "ADR 0012"
---

# Overview

With modules ([ADR 0009](0009-terraform-module-structure-and-cicd.md)) and
the three-Lambda topology ([ADR 0011](0011-extract-stage-alt-base-image-and-lambda-count.md))
settled, wiring the deployable root stack raised four decisions: bucket/ECR
names default to a `capitol-lake` prefix (S3 names are globally unique); the
extract Lambda receives only SSM *parameter names* as env vars, not secret
values, with the actual `ssm:GetParameter` runtime call left as follow-up;
the bronze bucket's S3 event notification is scoped to the `bronze/senate/`
prefix and `.html` suffix so it doesn't double-process House filings (which
already enqueue via SQS, per
[ADR 0011](0011-extract-stage-alt-base-image-and-lambda-count.md)); and the
House EventBridge schedule's filing year is a static, hand-bumped input
rather than one computed from `timestamp()`, to keep `plan` idempotent.[^adr]

[^adr]: ADR 0012
