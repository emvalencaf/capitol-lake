---
type: Pipeline Stage
title: "Stage 3: Ticker resolution and LLM fallback"
description: Null tickers are resolved through OpenFIGI/EDGAR; an optional LLM fallback recovers other null fields where the extractor is measurably weak.
resource: ../../../docs/architecture.md
tags: [pipeline, ticker-resolution, llm-fallback]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: architecture-doc
    resource: ../../../docs/architecture.md
    title: Architecture
---

# Overview

A [Transaction](/vocabulary/transaction.md) with a still-null `ticker` (after
the extractor's own printed-symbol match) goes through an OpenFIGI + EDGAR
resolution cascade. Separately, an optional LLM fallback stage can recover
specific null fields from a Filing's own source text — gated per field on the
evaluation harness's current accuracy for that field and kind, so it only
runs where the extractor is measurably weak, never unconditionally on every
null.[^architecture-doc]

As of [ADR 0011](/decisions/0011-extract-stage-alt-base-image-and-lambda-count.md),
this stage has no independent Lambda: it runs inside the same `extract`
Lambda handler as [extraction](extract.md) itself.

# Next stage

[Quality gate](quality-gate.md).

[^architecture-doc]: Architecture
