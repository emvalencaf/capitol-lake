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

Unlike `house_collect_handler.py`, this handler never enqueues an SQS
message itself: per #18/#43's orchestration shape, House chains into
extract via SQS because it's the one scheduled, automated collector, but
Senate has no schedule to chain from. Once this handler's `write_bytes`
lands a bronze object in S3 (whether invoked as a real Lambda or run
locally), an S3 event notification on the bronze bucket (infra, not code)
triggers the extract stage directly for that object — the same entry point
a human's manual upload would use, so the chain doesn't care which path put
the object there.
"""

import json
import os
from datetime import UTC, datetime
from urllib.request import Request, urlopen

import boto3

from capitol_lake.stages.senate_collect import collect_senate

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

    return collect_senate(
        event["response"],
        fetch_filing=_fetch,
        read_existing_sha256=lambda meta_key: _read_existing_sha256(s3_client, meta_key),
        write_bytes=lambda key, data: _write_bytes(s3_client, key, data),
        now=lambda: datetime.now(UTC).isoformat(),
    )
