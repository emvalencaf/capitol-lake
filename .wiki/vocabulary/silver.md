---
type: Domain Term
title: Silver
description: The layer of structured Filings and Transactions extracted from Bronze, keeping every line and its provenance.
tags: [vocabulary, layers]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: context-doc
    resource: ../../CONTEXT.md
    title: CONTEXT.md
---

# Overview

The layer of structured [Filings](filing.md) and [Transactions](transaction.md)
extracted from [Bronze](bronze.md), keeping every line and its
provenance.[^context-doc] Avoid: Clean, curated.

Written by [Stage 5: Silver write](/architecture/stages/silver-write.md) as
Hive-partitioned Parquet — see
[ADR 0008](/decisions/0008-silver-storage-stays-parquet-part-per-doc-id.md).

[^context-doc]: CONTEXT.md
