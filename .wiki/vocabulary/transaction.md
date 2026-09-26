---
type: Domain Term
title: Transaction
description: One line of a Filing describing a single purchase, sale or exchange of an asset.
tags: [vocabulary, disclosures]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: context-doc
    resource: ../../CONTEXT.md
    title: CONTEXT.md
---

# Overview

One line of a [Filing](filing.md) describing a single purchase, sale or
[exchange](exchange.md) of an asset.[^context-doc] Each Transaction has an
[Owner](owner.md) and a [Value range](value-range.md), and is extracted at
[Stage 2: Extract](/architecture/stages/extract.md). Avoid: Trade, row,
record.

[^context-doc]: CONTEXT.md
