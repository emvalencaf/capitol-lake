---
type: Pipeline Stage
title: "Stage 5: Silver write"
description: Filing and Transaction rows are serialized to Hive-partitioned Parquet, one part file per filing per table.
resource: ../../../docs/architecture.md
tags: [pipeline, silver, write]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: architecture-doc
    resource: ../../../docs/architecture.md
    title: Architecture
---

# Overview

[Filing](/vocabulary/filing.md) and [Transaction](/vocabulary/transaction.md)
rows are serialized to Hive-partitioned Parquet
(`silver/<table>/chamber=.../year=...`), one `part-<doc_id>.parquet` file per
filing per table, so reprocessing a filing overwrites its own file instead of
duplicating rows. No compaction job runs — at current House/Senate volume,
many small part files per partition is an accepted cost, not a problem being
solved yet.[^architecture-doc] See
[ADR 0008](/decisions/0008-silver-storage-stays-parquet-part-per-doc-id.md).

Per [ADR 0011](/decisions/0011-extract-stage-alt-base-image-and-lambda-count.md),
ticker resolution, LLM fallback, and the Silver write all currently happen
inside the same `extract` Lambda handler for the House path — there is no
separate "silver-write" Lambda, because no independent behavior exists at
that seam yet.

# Previous stages

[Collect](collect.md) → [Extract](extract.md) →
[Ticker resolution / LLM fallback](ticker-resolution.md) →
[Quality gate](quality-gate.md) → Silver write.

[^architecture-doc]: Architecture
