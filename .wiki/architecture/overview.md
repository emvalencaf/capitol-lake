---
type: Architecture Overview
title: Capitol Lake pipeline architecture
description: How a disclosure travels from collection to Silver, and the AWS services that carry it.
resource: ../../docs/architecture.md
tags: [architecture, pipeline, aws]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: architecture-doc
    resource: ../../docs/architecture.md
    title: Architecture
---

# Overview

Capitol Lake turns a member of Congress's stock-trading disclosure (a PTR — see
[PTR](/vocabulary/ptr.md)) into queryable Silver rows. The full narrative,
including the system-architecture and Bronze-to-Silver data-flow diagrams,
lives in `docs/architecture.md`[^architecture-doc];
this concept indexes it rather than restating it, and links into the bundle's
own concepts for the pieces that benefit from being independently addressable.

House collection and extraction are fully automated; Senate collection is
automated with a manual fallback, because the Senate's disclosure site blocks
automated traffic from cloud IP ranges (see
[ADR 0013](/decisions/0013-senate-html-extraction-design.md)). Everything runs
on AWS Lambda (packaged as container images, see
[ADR 0001](/decisions/0001-lambda-container-image-packaging.md) and
[ADR 0011](/decisions/0011-extract-stage-alt-base-image-and-lambda-count.md)),
triggered on a schedule, with S3 as the only durable storage, and the AWS
account wired up per [ADR 0009](/decisions/0009-terraform-module-structure-and-cicd.md),
[ADR 0010](/decisions/0010-finops-tag-filtered-budget.md) and
[ADR 0012](/decisions/0012-terraform-root-stack-wiring.md).

# Pipeline stages

See [the stages index](stages/index.md) for one concept per stage: collect,
extract, ticker resolution / LLM fallback, quality gate, and Silver write.

# Domain vocabulary

See [the vocabulary index](/vocabulary/index.md) for the terms this doc and
the codebase use (Filing, Transaction, Bronze, Silver, etc.), sourced from
`CONTEXT.md` at the repository root.

[^architecture-doc]: Architecture
