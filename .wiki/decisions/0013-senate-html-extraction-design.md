---
type: Decision
title: "ADR 0013: Senate HTML extraction -- no doc-id cross-check, Exchange as one row with two legs"
description: The Senate extractor trusts the bronze key's doc_id with no integrity check, and keeps an Exchange as a single Transaction row matching the source's own layout.
resource: ../../docs/adr/0013-senate-html-extraction-design.md
tags: [decision, extract, senate]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0013-senate-html-extraction-design.md
    title: "ADR 0013"
---

# Overview

Unlike a House PTR, a Senate `/ptr/` filing page carries no document
identifier of its own to cross-check against the bronze key's `doc_id`.
Decided: `extract_senate_filing` takes `doc_id` from the bronze key alone
with no integrity check analogous to House's `DocIdMismatchError` — a real,
if narrow, loss of that safety net.[^adr]

Separately: the Senate PTR table renders an
[Exchange](/vocabulary/exchange.md) as one row with two asset lines with no
structured split in the source. Decided: this stays one
[Transaction](/vocabulary/transaction.md) row, with the asset given up in
`asset_description` and the asset received kept verbatim in `description`.
`notification_date`, `filing_status` and `sub_owner` have no structured
source in the Senate page and stay null, per
[ADR 0002](0002-scanned-filing-fields-null-not-zonal-ocr.md)'s null-over-
guessed precedent.

[^adr]: ADR 0013
