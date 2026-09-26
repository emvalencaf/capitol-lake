---
type: Domain Term
title: Digital filing
description: A Filing submitted as a text-layer PDF, extractable directly without OCR.
tags: [vocabulary, disclosures]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: context-doc
    resource: ../../CONTEXT.md
    title: CONTEXT.md
---

# Overview

A [Filing](filing.md) submitted as a text-layer PDF, extractable directly
without OCR.[^context-doc] Avoid: Native PDF.

Parsed by validating printed field labels before trusting the value beside
them — see
[ADR 0003](/decisions/0003-digital-parser-label-validated-positional-walk.md).

[^context-doc]: CONTEXT.md
