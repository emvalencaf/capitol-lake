---
type: Pipeline Stage
title: "Stage 4: Quality gate"
description: Pure checks over a run's aggregate statistics that can veto a Silver overwrite; implemented but not yet wired into any handler.
resource: ../../../docs/architecture.md
tags: [pipeline, quality-gate]
status: draft
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: architecture-doc
    resource: ../../../docs/architecture.md
    title: Architecture
---

# Overview

A per-run quality gate exists as a set of pure checks over a run's aggregate
statistics — a volume-regression check, a completeness check against fields
that should never be null, and a row-count-divergence check against the
collector's own announced count. It lets a caller skip a
[Silver](/vocabulary/silver.md) overwrite when a run looks unhealthy, without
touching S3 or a prior-run store itself.[^architecture-doc]

**Status note.** As of the architecture doc's last update, no Lambda handler
calls this gate yet — it's implemented and tested as a pure function, but the
orchestration wiring to invoke it automatically on every run is still open.
Treat this stage as designed but not yet load-bearing in production; hence
`status: draft` here rather than `stable`.

# Next stage

[Silver write](silver-write.md).

[^architecture-doc]: Architecture
