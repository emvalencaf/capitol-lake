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
never for a `noop` key, so an unchanged filing already in bronze isn't
re-queued for extraction. `EXTRACT_QUEUE_URL` is the extract stage's queue;
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
from shared.orchestration import extract_queue_message

USER_AGENT = "capitol-lake collector (contact: edsonmvf@gmail.com)"
BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")
EXTRACT_QUEUE_URL = os.environ.get("EXTRACT_QUEUE_URL")


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        return response.read()


def _read_existing_sha256(s3_client, meta_key: str) -> str | None:
    try:
        obj = s3_client.get_object(Bucket=BRONZE_BUCKET, Key=meta_key)
    except s3_client.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())["sha256"]


def _write_bytes(s3_client, key: str, data: bytes) -> None:
    s3_client.put_object(Bucket=BRONZE_BUCKET, Key=key, Body=data)


def _enqueue_written_filings(sqs_client, written: list[str]) -> None:
    for bronze_key in written:
        sqs_client.send_message(
            QueueUrl=EXTRACT_QUEUE_URL,
            MessageBody=json.dumps(extract_queue_message(bronze_key)),
        )


def handler(event: dict, context: object) -> dict:
    s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

    result = collect_house(
        event["year"],
        fetch_index=_fetch,
        fetch_filing=_fetch,
        read_existing_sha256=lambda meta_key: _read_existing_sha256(s3_client, meta_key),
        write_bytes=lambda key, data: _write_bytes(s3_client, key, data),
        now=lambda: datetime.now(UTC).isoformat(),
    )

    if EXTRACT_QUEUE_URL:
        sqs_client = boto3.client("sqs", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_SQS"))
        _enqueue_written_filings(sqs_client, result["written"])

    return result
