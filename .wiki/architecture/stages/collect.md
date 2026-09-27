---
type: Pipeline Stage
title: "Stage 1: Collect (Bronze)"
description: House and Senate collectors write raw, unedited filings into the Bronze layer.
resource: ../../../docs/architecture.md
tags: [pipeline, bronze, collect]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: architecture-doc
    resource: ../../../docs/architecture.md
    title: Architecture
---

# Overview

The first pipeline stage writes each [Filing](/vocabulary/filing.md) to
[Bronze](/vocabulary/bronze.md) byte-for-byte, exactly as published — Bronze
never edits or re-encodes what it collects.[^architecture-doc]

**House.** A scheduled Lambda, triggered daily by EventBridge, lists that
year's House PTR filings and downloads any Filing not already in Bronze
(`house_collect.py`). A successful write enqueues the new bronze key onto the
extract stage's SQS queue.

**Senate.** The Senate's eFD search UI blocks bot and cloud-fingerprinted
traffic, so the Senate collector runs two ways: an automated Lambda driving a
real headless-browser session, and a manual fallback (a human runs the same
flow locally and uploads the result) for whenever the automated path doesn't
clear the block. Both paths write to the same Bronze bucket; there is no
EventBridge schedule for Senate, so a bronze write triggers the next stage
directly via an S3 event notification, not an SQS enqueue.

Every collector Lambda ships as a container image from ECR — see
[ADR 0001](/decisions/0001-lambda-container-image-packaging.md) and
[ADR 0011](/decisions/0011-extract-stage-alt-base-image-and-lambda-count.md).
The S3-event scope that routes only Senate bronze writes (not House's) to
extract is [ADR 0012](/decisions/0012-terraform-root-stack-wiring.md).

# Next stage

[Extract, by chamber and filing kind](extract.md).

[^architecture-doc]: Architecture
