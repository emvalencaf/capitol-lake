"""Thin Lambda adapter for the House collector.

Wires a Lambda event's `year` to `collect_house` with real HTTP fetches
(stdlib `urllib`, ~1 request/second) and a real S3 bronze bucket (`boto3`,
bundled in the Lambda Python base image). Handlers stay thin by convention:
they only translate the event shape and real clients into the pure
function's arguments and are not unit-tested (see docs/local-dev.md); the
pure function underneath is.

Per the orchestration shape settled in #18, House is the one scheduled,
fully-automated collector, so this handler also enqueues one SQS message
(`orchestration.extract_queue_message`, an S3-key reference only, never
document bytes) per bronze key `collect_house` actually wrote this run —
never for a `skipped` key (a `doc_id` already on record, never even
fetched — see `collect_house`'s docstring), so an unchanged filing already
in bronze isn't re-queued for extraction. `EXTRACT_QUEUE_URL` is the extract
stage's queue;
left unset, this stage still writes bronze but chains nothing further,
which keeps the handler runnable standalone (e.g. against MinIO with no
queue configured) exactly like every other stage here.
"""

import json
import os
from datetime import UTC, datetime
from urllib.request import Request, urlopen

import boto3

from house_collect.collect import collect_house
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


def _known_doc_ids(s3_client, prefix: str) -> set[str]:
    doc_ids: set[str] = set()
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BRONZE_BUCKET, Prefix=prefix):
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
    with wide_event("house_collect", context) as log:
        log["year"] = event.get("year")

        s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

        result = collect_house(
            event["year"],
            fetch_index=_fetch,
            fetch_filing=_fetch,
            known_doc_ids=lambda: _known_doc_ids(
                s3_client, f"bronze/house/year={event['year']}/"
            ),
            write_bytes=lambda key, data: _write_bytes(s3_client, key, data),
            now=lambda: datetime.now(UTC).isoformat(),
            on_progress=lambda progress: log_progress("house_collect", context, **progress),
        )
        log["written_count"] = len(result["written"])
        log["skipped_count"] = len(result["skipped"])

        if EXTRACT_QUEUE_URL:
            sqs_client = boto3.client("sqs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_SQS"))
            _enqueue_written_filings(sqs_client, result["written"])
            log["enqueued_count"] = len(result["written"])

        return result
