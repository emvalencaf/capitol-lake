---
type: Decision
title: "ADR 0010: FinOps -- tag-filtered AWS Budget with dedicated SNS alerts"
description: A single AWS Budget scoped to the Project=capitol-lake tag alerts via a dedicated SNS topic, isolating project spend from the shared account.
resource: ../../docs/adr/0010-finops-tag-filtered-budget.md
tags: [decision, finops, cost]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0010-finops-tag-filtered-budget.md
    title: "ADR 0010"
---

# Overview

The AWS account hosting Capitol Lake is shared with other workloads, so an
account-wide Budget would conflate their spend with the project's near-zero
target. Decided: a single AWS Budget scoped to the `Project=capitol-lake`
cost allocation tag, alerting at 50%/80%/100% of a $5/month budget plus a
forecasted-to-100% alert, via a dedicated SNS topic with an email
subscription. All Terraform-managed resources get `Project`, `Environment`,
`Chamber`, `Stage` and `ManagedBy` tags through provider-level
`default_tags`.[^adr]

Cost-allocation tags must be activated in the AWS Billing Console before the
tag-filtered Budget can see tagged spend — tracked as a separate manual task,
not a Terraform resource.

[^adr]: ADR 0010
