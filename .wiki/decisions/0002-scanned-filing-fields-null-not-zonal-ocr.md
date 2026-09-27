---
type: Decision
title: "ADR 0002: Accept null transaction type, cap-gains and value-range for scanned filings, no zonal OCR"
description: Scanned House PTR checkbox columns (transaction type, capital gains, value range) are reported null with low confidence rather than resolved by an unverified zonal-OCR pass.
resource: ../../docs/adr/0002-scanned-filing-fields-null-not-zonal-ocr.md
tags: [decision, ocr, scanned-filing]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0002-scanned-filing-fields-null-not-zonal-ocr.md
    title: "ADR 0002"
---

# Overview

Full-page OCR on [scanned filings](/vocabulary/scanned-filing.md) garbles the
`transaction_type` and `cap_gains` checkbox columns, while asset name and
dates survive. A fixed-crop "zonal OCR" pass could recover them but rests on
an unverified assumption (identical paper-form layout across years/filers)
and was out of budget for Phase 1+2. Decided: report these fields null with
low confidence — an honest result the silver schema's confidence/provenance
columns make explicit, not a defect.[^adr]

An addendum (#37) extends the same reasoning to
[value range](/vocabulary/value-range.md), also a lettered checkbox grid on
scanned filings, and clarifies that `cap_gains` does not yet exist as a
schema field at all.

[^adr]: ADR 0002
