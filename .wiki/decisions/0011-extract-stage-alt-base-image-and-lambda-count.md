---
type: Decision
title: "ADR 0011: Extract stage packaging (Debian base image) and actual Lambda count (three, not four)"
description: The extract Lambda uses a Debian alternative base image for Tesseract via apt, and the pipeline stays a three-Lambda topology since ticker/LLM-fallback and Silver write have no independent behavior.
resource: ../../docs/adr/0011-extract-stage-alt-base-image-and-lambda-count.md
tags: [decision, lambda, packaging]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0011-extract-stage-alt-base-image-and-lambda-count.md
    title: "ADR 0011"
---

# Overview

Neither the AWS Lambda Python 3.12 base image nor plain `amazonlinux:2023`
carries a `tesseract` package, so
[ADR 0001](0001-lambda-container-image-packaging.md)'s "plain package
manager" intent was resolved with `python:3.12-slim` plus `apt-get install
tesseract-ocr`, `awslambdaric`, and the Runtime Interface Emulator for local
testing; every other stage's image stays on the AWS base image.[^adr]

Separately: the design named four Lambdas (collect, extract,
ticker/LLM-fallback, silver-write), but by implementation time ticker
resolution, LLM fallback, and Silver write all lived in
`extract_handler.py` with no independent pure-function boundary. Decided:
keep a three-Lambda topology (`house-collect`, `senate-collect`, `extract`),
with `extract`'s SQS queue given a higher visibility timeout to cover its
ticker/LLM-fallback work.

[^adr]: ADR 0011
