---
type: Domain Term
title: Exchange
description: A Transaction in which one asset is given up and a different asset is received in the same reported line.
tags: [vocabulary, disclosures]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: context-doc
    resource: ../../CONTEXT.md
    title: CONTEXT.md
---

# Overview

A [Transaction](transaction.md) in which one asset is given up and a
different asset is received in the same reported line, rather than a simple
purchase or sale. The asset given up is the Transaction's asset; the asset
received is recorded separately and never treated as its own
Transaction.[^context-doc] Avoid: Swap, trade-in.

The Senate HTML extractor renders an Exchange as one row with two asset
lines rather than a structured split — see
[ADR 0013](/decisions/0013-senate-html-extraction-design.md).

[^context-doc]: CONTEXT.md
