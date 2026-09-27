---
type: Decision
title: "ADR 0014: Shared package plus one top-level package per Lambda"
description: Split the flat src/capitol_lake package into src/shared plus one top-level package per Lambda, so each Docker image ships only its own code and shared.
resource: ../../docs/adr/0014-shared-plus-per-lambda-src-layout.md
tags: [decision, packaging, src-layout]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0014-shared-plus-per-lambda-src-layout.md
    title: "ADR 0014"
---

# Overview

The single `src/capitol_lake` package meant every Lambda's Docker image
shipped every other Lambda's code too (one `COPY` of the whole tree).
Decided: split into `src/shared/` (code used by 2+ Lambda images, found by
tracing every cross-module import — `schema`, `keys`, `llm_providers`,
`bronze_write`, `orchestration`, plus new `doc_id.py` and `senate_index.py`
splits) and one top-level package per Lambda (`house_collect`,
`senate_collect`, `senate_collect_automated`, `senate_akamai_probe`,
`extract_data`, `stub`), each with its own `handler.py`. Each Dockerfile now
does two `COPY`s — `shared` plus its own package — instead of one. Tests
mirror the same split under `tests/units/`.[^adr]

[^adr]: ADR 0014
