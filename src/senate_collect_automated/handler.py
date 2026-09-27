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

Like `senate_collect/handler.py`, this never enqueues an SQS message itself:
Senate has no schedule to chain from (#18), so an S3 event notification on
the bronze bucket (infra, not code) forwards whatever this handler writes
onto extract's own SQS queue, the same path House's own messages take.
"""

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime

import boto3

from senate_collect_automated.browser_session import run_senate_efd_session

BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")


def _read_existing_sha256(s3_client, meta_key: str) -> str | None:
    try:
        obj = s3_client.get_object(Bucket=BRONZE_BUCKET, Key=meta_key)
    except s3_client.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())["sha256"]


def _write_bytes(s3_client, key: str, data: bytes) -> None:
    s3_client.put_object(Bucket=BRONZE_BUCKET, Key=key, Body=data)


def handler(event: dict, context: object) -> dict:
    s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

    result = run_senate_efd_session(
        read_existing_sha256=lambda meta_key: _read_existing_sha256(s3_client, meta_key),
        write_bytes=lambda key, data: _write_bytes(s3_client, key, data),
        now=lambda: datetime.now(UTC).isoformat(),
    )

    return asdict(result)
