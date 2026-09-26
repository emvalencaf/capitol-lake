---
type: Pipeline Stage
title: "Stage 2: Extract, by chamber and filing kind"
description: Raw filing bytes become structured Filing and Transaction rows, routed by chamber and filing kind.
resource: ../../../docs/architecture.md
tags: [pipeline, extract]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: architecture-doc
    resource: ../../../docs/architecture.md
    title: Architecture
---

# Overview

A House [Filing](/vocabulary/filing.md) routes to a
[digital](/vocabulary/digital-filing.md) or
[scanned](/vocabulary/scanned-filing.md) parser depending on which kind of
document it is; a Senate Filing goes to the one HTML extractor there is.
Every row extracted is kept regardless of asset type — this stage routes and
serializes, it never filters a row out.[^architecture-doc]

- **House digital.** Parses text-layer PDFs by validating printed field
  labels before trusting the value beside them, rather than reading a fixed
  line offset — see
  [ADR 0003](/decisions/0003-digital-parser-label-validated-positional-walk.md).
- **House scanned.** OCR reliably recovers asset name and dates but not the
  transaction-type or value-range checkboxes, which come back null with low
  confidence rather than guessed — see
  [ADR 0002](/decisions/0002-scanned-filing-fields-null-not-zonal-ocr.md).
- **Senate HTML.** The one Senate `/ptr/` page format has no document id of
  its own to cross-check against, and renders an
  [Exchange](/vocabulary/exchange.md) as a single row with two asset lines —
  see [ADR 0013](/decisions/0013-senate-html-extraction-design.md).

# Next stage

[Ticker resolution and LLM fallback](ticker-resolution.md).

[^architecture-doc]: Architecture
