---
type: Domain Term
title: Filing
description: One submitted PTR document, identified by its chamber and document id.
tags: [vocabulary, disclosures]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: context-doc
    resource: ../../CONTEXT.md
    title: CONTEXT.md
---

# Overview

One submitted [PTR](ptr.md) document, identified by its chamber and document
id.[^context-doc] A Filing is either a [digital](digital-filing.md) or
[scanned](scanned-filing.md) House document, or a Senate HTML page, and holds
one or more [Transaction](transaction.md) lines. Avoid: Report, disclosure
(when meaning a single document).

Filings are collected untouched into [Bronze](bronze.md) and refined into
[Silver](silver.md) — see [Stage 1: Collect](/architecture/stages/collect.md).

[^context-doc]: CONTEXT.md
