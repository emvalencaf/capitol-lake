---
type: Decision
title: "ADR 0015: Senate→extract via SQS, not a direct S3-to-Lambda invoke"
description: Route the bronze bucket's Senate S3 event notification through extract's own SQS queue instead of invoking extract directly, so Senate-triggered failures get the same retry/DLQ handling House's already have.
resource: ../../docs/adr/0015-senate-extract-via-sqs-not-direct-invoke.md
tags: [decision, terraform, orchestration, reliability]
status: stable
generated: { by: claude-code/sonnet-5, at: 2026-09-26T00:00:00Z }
sources:
  - id: adr
    resource: ../../docs/adr/0015-senate-extract-via-sqs-not-direct-invoke.md
    title: "ADR 0015"
---

# Overview

House's collector chains into `extract` over SQS, so a failed extract
invocation gets retried and eventually dead-lettered. Senate's bronze
writes instead invoked `extract`'s Lambda directly off an S3 event
notification, with no SQS message behind it — so a failed Senate-triggered
extract had nothing to retry or DLQ
(`shared.orchestration.BronzeKeyRecord.message_id` was always `None` for an
S3-sourced record). Decided: the bronze bucket's S3 event notification now
targets extract's own SQS queue instead of the Lambda directly (an
`aws_sqs_queue_policy` scopes `s3.amazonaws.com`'s `sqs:SendMessage` to the
bronze bucket's ARN), giving Senate-triggered messages the same retry/DLQ
handling House's already had.
`shared.orchestration.bronze_key_records_from_event` was extended to unpack
an SQS record whose body is a forwarded S3 event notification (rather than
House's own `{"bronze_key": ...}` shape), pairing every bronze key it finds
with the *outer* SQS record's `messageId`.[^adr]

[^adr]: ADR 0015
