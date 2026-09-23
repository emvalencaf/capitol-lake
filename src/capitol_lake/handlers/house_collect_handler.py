"""Thin Lambda adapter for the House collector.

Wires a Lambda event's `year` to `collect_house` with real HTTP fetches
(stdlib `urllib`, ~1 request/second) and a real S3 bronze bucket (`boto3`,
bundled in the Lambda Python base image). Handlers stay thin by convention:
they only translate the event shape and real clients into the pure
function's arguments and are not unit-tested (see docs/local-dev.md); the
pure function underneath is.
"""

import json
import os
from datetime import UTC, datetime
from urllib.request import Request, urlopen

import boto3

from capitol_lake.stages.house_collect import collect_house

USER_AGENT = "capitol-lake collector (contact: edsonmvf@gmail.com)"
BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")


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


def handler(event: dict, context: object) -> dict:
    s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

    return collect_house(
        event["year"],
        fetch_index=_fetch,
        fetch_filing=_fetch,
        read_existing_sha256=lambda meta_key: _read_existing_sha256(s3_client, meta_key),
        write_bytes=lambda key, data: _write_bytes(s3_client, key, data),
        now=lambda: datetime.now(UTC).isoformat(),
    )
