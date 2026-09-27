"""Thin Lambda adapter for the Senate collector.

Unlike the House collector, this stage is not scheduled: per #18, the Senate
eFD search UI is Akamai bot/fingerprint-protected, so a human (or a local
headless-browser step) runs the search, captures the JSON body the eFD
search UI's own DataTables endpoint returns, and invokes this handler (or
the underlying `collect_senate` directly) with that capture as
`event["response"]`. Individual `/ptr/` filing pages are then fetched over
plain HTTP (stdlib `urllib`, ~1 request/second) and written to a real S3
bronze bucket (`boto3`, bundled in the Lambda Python base image) — this only
works where the Akamai check passes; see `docs/local-dev.md` for what's
confirmed to clear it. Handlers stay thin by convention: they only translate
the event shape and real clients into the pure function's arguments and are
not unit-tested (see docs/local-dev.md); the pure function underneath is.

Like `house_collect/handler.py`, this handler enqueues one SQS message
(`orchestration.extract_queue_message`, an S3-key reference only, never
document bytes) per bronze key `collect_senate` actually wrote this run —
never for a `skipped` key. Previously this stage relied on an S3 event
notification on the bronze bucket to forward its writes onto extract's own
SQS queue instead (ADR-0015); that indirection is gone (ADR-0016) — this
handler now owns enqueuing exactly like every other collector.
`EXTRACT_QUEUE_URL` is the extract stage's queue; left unset, this stage
still writes bronze but chains nothing further, which keeps the handler
runnable standalone (e.g. against MinIO with no queue configured) exactly
like every other stage here.

`_known_doc_ids` lists the whole `bronze/senate/` prefix (every year, not
just one) since a captured search response can span a year boundary
(`collect_senate`'s own `years` output can hold more than one) — cheap here
since Senate's corpus is much smaller than House's (ADR-0018).
"""

import json
import os
from datetime import UTC, datetime
from urllib.request import Request, urlopen

import boto3

from senate_collect.collect import collect_senate
from shared.keys import UnrecognizedBronzeKeyError, parse_bronze_key
from shared.orchestration import extract_queue_message
from shared.wide_event import log_progress, wide_event

USER_AGENT = "capitol-lake collector (contact: edsonmvf@gmail.com)"
BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")
EXTRACT_QUEUE_URL = os.environ.get("EXTRACT_QUEUE_URL")


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        return response.read()


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
    with wide_event("senate_collect", context) as log:
        s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

        result = collect_senate(
            event["response"],
            fetch_filing=_fetch,
            known_doc_ids=lambda: _known_doc_ids(s3_client),
            write_bytes=lambda key, data: _write_bytes(s3_client, key, data),
            now=lambda: datetime.now(UTC).isoformat(),
            on_progress=lambda progress: log_progress("senate_collect", context, **progress),
        )
        log["years"] = result["years"]
        log["written_count"] = len(result["written"])
        log["skipped_count"] = len(result["skipped"])

        if EXTRACT_QUEUE_URL:
            sqs_client = boto3.client("sqs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_SQS"))
            _enqueue_written_filings(sqs_client, result["written"])
            log["enqueued_count"] = len(result["written"])

        return result
