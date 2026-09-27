---
type: Domain Term
title: Scanned filing
description: A Filing submitted as a scanned paper form, requiring OCR; some fields are unreliable to extract from these.
tags: [vocabulary, disclosures]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: context-doc
    resource: ../../CONTEXT.md
    title: CONTEXT.md
---

# Overview

A [Filing](filing.md) submitted as a scanned paper form, requiring OCR; some
fields (transaction type, capital-gains flag) are unreliable to extract from
these.[^context-doc] Avoid: Image filing, OCR filing.

See [ADR 0002](/decisions/0002-scanned-filing-fields-null-not-zonal-ocr.md)
for why those fields are reported null rather than guessed.

[^context-doc]: CONTEXT.md
