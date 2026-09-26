---
type: Decision
title: "ADR 0008: Silver stays Parquet on S3, one part-<doc_id>.parquet per filing, no compaction"
description: Silver keeps its pre-cloud Hive-partitioned Parquet layout rather than moving to Iceberg, deferring any catalog decision.
resource: ../../docs/adr/0008-silver-storage-stays-parquet-part-per-doc-id.md
tags: [decision, silver, storage]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0008-silver-storage-stays-parquet-part-per-doc-id.md
    title: "ADR 0008"
---

# Overview

Iceberg would offer schema evolution and time travel, but only pays off with
a catalog, and the LocalStack Hobby tier has no free Glue/Athena to develop
against. Decided: [Silver](/vocabulary/silver.md) keeps its Hive-partitioned
Parquet layout on S3 unchanged; each Lambda invocation writes its own
`part-<doc_id>.parquet` file, so reprocessing a filing overwrites its own
file instead of duplicating rows. No compaction job is introduced — at
current volume, many small part files per partition is an accepted
cost.[^adr]

Implemented by [Stage 5: Silver write](/architecture/stages/silver-write.md).

[^adr]: ADR 0008
