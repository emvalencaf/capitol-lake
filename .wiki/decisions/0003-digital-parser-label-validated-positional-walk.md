---
type: Decision
title: "ADR 0003: Digital parser validates labels before accepting positional field values"
description: The digital-PDF parser matches stripped, normalized field labels before trusting an adjacent value, instead of reading a fixed line offset.
resource: ../../docs/adr/0003-digital-parser-label-validated-positional-walk.md
tags: [decision, parsing, digital-filing]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0003-digital-parser-label-validated-positional-walk.md
    title: "ADR 0003"
---

# Overview

pypdf renders bold section/row labels with unpredictable internal whitespace,
so literal label matching fails and a pure positional walk risks silently
misattributing text when an optional line is absent. Decided: the
[digital filing](/vocabulary/digital-filing.md) parser drops section headers
as anchors, strips whitespace from each candidate line, and matches it
against a small fixed label dictionary before accepting the adjacent value —
turning a missing line into a clean null (the same honest-null precedent as
[ADR 0002](0002-scanned-filing-fields-null-not-zonal-ocr.md)) rather than a
guess.[^adr]

Addenda cover a pypdf 6 NUL-character garbling variant, row boundaries
delimited by vertical whitespace rather than text, and filling `ticker` from
a filer's own printed stock/ETF symbol.

[^adr]: ADR 0003
