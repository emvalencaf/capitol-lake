---
type: Decision
title: "ADR 0001: Lambda packaged as a container image, not zip + layers"
description: The extraction Lambda ships as an ECR container image so Tesseract installs via a plain package manager, keeping local and production environments symmetric.
resource: ../../docs/adr/0001-lambda-container-image-packaging.md
tags: [decision, lambda, packaging]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0001-lambda-container-image-packaging.md
    title: "ADR 0001"
---

# Overview

The extraction Lambda needs Tesseract plus several Python libraries. A zip +
layers split would fit Lambda's size limits, but every real-world reference
for Tesseract-on-Lambda packages it as a container image, since that lets
Tesseract install via a plain `yum`/`apt` call instead of a hand-built binary
matched to the runtime's OS/architecture. Container image (ECR) was chosen
for both local and production, keeping the two symmetric via the Lambda
Runtime Interface Emulator.[^adr]

Resolved further, once the Tesseract package proved unavailable on the AWS
base image, by
[ADR 0011](0011-extract-stage-alt-base-image-and-lambda-count.md).

[^adr]: ADR 0001
