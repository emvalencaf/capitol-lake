"""Thin Lambda adapter for the automated Senate collector (#68).

Wires a Lambda event into #67's
`senate_collect_automated.browser_session.run_senate_efd_session` flow with
real S3 access (`boto3`, same `BRONZE_BUCKET` env-var convention as every
other handler). Unlike `senate_collect/handler.py`, this handler takes no
`event["response"]` capture — the Playwright session drives the search
itself — so `event` is unused, kept only to match the Lambda handler
signature. Handlers stay thin by convention: they only translate real
clients into the flow's arguments and are not unit-tested (see
docs/local-dev.md); the flow underneath is exercised by hand, the same
convention `senate_akamai_probe/probe.py` follows.

Like `house_collect/handler.py`, this handler enqueues one SQS message
(`orchestration.extract_queue_message`, an S3-key reference only, never
document bytes) per bronze key this run actually wrote — never for a
`skipped` key. Previously this relied on an S3 event notification on the
bronze bucket to forward writes onto extract's own SQS queue instead
(ADR-0015); that indirection is gone (ADR-0016) — every collector now owns
enqueuing its own writes directly. `EXTRACT_QUEUE_URL` is the extract
stage's queue; left unset, this stage still writes bronze but chains
nothing further, which keeps the handler runnable standalone (e.g. against
MinIO with no queue configured) exactly like every other stage here.

`_known_doc_ids` lists the whole `bronze/senate/` prefix (every year), same
as `senate_collect/handler.py` (ADR-0018).
"""

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime

import boto3

from senate_collect_automated.browser_session import run_senate_efd_session
from shared.keys import UnrecognizedBronzeKeyError, parse_bronze_key
from shared.orchestration import extract_queue_message
from shared.wide_event import log_progress, wide_event

BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")
EXTRACT_QUEUE_URL = os.environ.get("EXTRACT_QUEUE_URL")


def _known_doc_ids(s3_client) -> set[str]:
    doc_ids: set[str] = set()
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BRONZE_BUCKET, Prefix="bronze/senate/"):
        for obj in page.get("Contents", []):
            try:
                doc_ids.add(parse_bronze_key(obj["Key"]).doc_id)
            except UnrecognizedBronzeKeyError:
                continue
    return doc_ids


def _write_bytes(s3_client, key: str, data: bytes) -> None:
    s3_client.put_object(Bucket=BRONZE_BUCKET, Key=key, Body=data)


def _enqueue_written_filings(sqs_client, written: list[str]) -> None:
    for bronze_key in written:
        sqs_client.send_message(
            QueueUrl=EXTRACT_QUEUE_URL,
            MessageBody=json.dumps(extract_queue_message(bronze_key)),
        )


def handler(event: dict, context: object) -> dict:
    with wide_event("senate_collect_automated", context) as log:
        s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

        result = run_senate_efd_session(
            known_doc_ids=lambda: _known_doc_ids(s3_client),
            write_bytes=lambda key, data: _write_bytes(s3_client, key, data),
            now=lambda: datetime.now(UTC).isoformat(),
            on_progress=lambda progress: log_progress(
                "senate_collect_automated", context, **progress
            ),
        )
        log["years"] = result.years
        log["filings_available"] = result.filings_available
        log["filings_processed"] = result.filings_processed
        log["written_count"] = len(result.written)
        log["skipped_count"] = len(result.skipped)

        if EXTRACT_QUEUE_URL:
            sqs_client = boto3.client("sqs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_SQS"))
            _enqueue_written_filings(sqs_client, result.written)
            log["enqueued_count"] = len(result.written)

        return asdict(result)
