---
type: Domain Term
title: Value range
description: The bracket of dollar amounts a Transaction falls in, as reported; disclosures never give an exact amount.
tags: [vocabulary, disclosures]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: context-doc
    resource: ../../CONTEXT.md
    title: CONTEXT.md
---

# Overview

The bracket of dollar amounts a [Transaction](transaction.md) falls in, as
reported; disclosures never give an exact amount.[^context-doc] Avoid:
Amount, value, price.

Null for scanned House filings, whose value-range column is a checkbox grid
OCR cannot reliably resolve — see
[ADR 0002](/decisions/0002-scanned-filing-fields-null-not-zonal-ocr.md).

[^context-doc]: CONTEXT.md
