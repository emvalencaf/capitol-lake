"""Stage-to-stage handoff (#43): translate a Lambda event into bronze keys.

Per the orchestration shape settled in #18, stages are chained via SQS
carrying only S3-key references, never inline document bytes: a queue
message is `{"bronze_key": ...}`, built by `extract_queue_message` and sent
by an upstream handler (`house_collect_handler`). The Senate side has no
scheduled collector (#18); once its bronze objects land in S3 (manually or
via `senate_collect_handler`), an S3 event notification on the bronze bucket
triggers the same downstream chain directly, without an SQS hop. A stage's
handler therefore has to unpack one of three event shapes: a plain
`{"bronze_key": ...}` invocation (manual/local/RIE testing, matching every
other handler's existing convention), an SQS event, or an S3 event —
`bronze_keys_from_event` is the one place that dispatches on all three, kept
here rather than duplicated in every downstream handler.
"""

from __future__ import annotations

import json
from typing import NamedTuple
from urllib.parse import unquote_plus


class UnrecognizedEventShapeError(ValueError):
    """A Lambda event matches none of the shapes this stage chain produces."""


class BronzeKeyRecord(NamedTuple):
    """One bronze key off an invocation's event, plus its retry handle.

    `message_id` is the SQS record's `messageId` when the key came off an
    SQS event (a handler's own `batchItemFailures` entry, on that record's
    failure, per #43's per-message DLQ posture) or `None` otherwise — a
    plain invocation or an S3 event has no SQS message to retry/DLQ, so a
    handler must never report a batch-item failure for one of those, even
    in a batch that mixes sources.
    """

    bronze_key: str
    message_id: str | None


def _bronze_key_record_from_sqs(record: dict) -> BronzeKeyRecord:
    bronze_key = json.loads(record["body"])["bronze_key"]
    return BronzeKeyRecord(bronze_key, record["messageId"])


def _bronze_key_record_from_s3(record: dict) -> BronzeKeyRecord:
    return BronzeKeyRecord(unquote_plus(record["s3"]["object"]["key"]), None)


_RECORD_PARSERS = {"aws:sqs": _bronze_key_record_from_sqs, "aws:s3": _bronze_key_record_from_s3}


def bronze_key_records_from_event(event: dict) -> list[BronzeKeyRecord]:
    """Extract every bronze key (with its retry handle) an event carries, in order.

    Dispatches on shape: a plain `{"bronze_key": ...}` invocation yields
    that one key with no `message_id`; an event with `Records` pairs each
    record's bronze key with its `messageId` when it's an SQS record (body
    is `{"bronze_key": ...}`, per `extract_queue_message`) or `None` when
    it's an S3 record (the record's own `s3.object.key`, URL-decoded since
    S3 event keys are `application/x-www-form-urlencoded`) — including a
    batch that mixes both record sources, which a handler's failure
    reporting must handle safely (see `BronzeKeyRecord`). Raises
    `UnrecognizedEventShapeError` for anything else, rather than silently
    skipping a record a future event source doesn't yet match.
    """
    if "bronze_key" in event:
        return [BronzeKeyRecord(event["bronze_key"], None)]
    if "Records" in event:
        records = []
        for record in event["Records"]:
            source = record.get("eventSource")
            parser = _RECORD_PARSERS.get(source)
            if parser is None:
                raise UnrecognizedEventShapeError(
                    f"unrecognized Lambda event record source: {source!r}"
                )
            records.append(parser(record))
        return records
    raise UnrecognizedEventShapeError(f"unrecognized Lambda event shape: {sorted(event)}")


def bronze_keys_from_event(event: dict) -> list[str]:
    """Just the bronze keys `bronze_key_records_from_event` extracts, without retry handles."""
    return [record.bronze_key for record in bronze_key_records_from_event(event)]


def extract_queue_message(bronze_key: str) -> dict:
    """Build the SQS message body handed from collect to the extract stage.

    Carries only the bronze S3 key, never document bytes; `chamber`/`year`/
    `doc_id` are cheap to re-derive from the key itself
    (`keys.parse_bronze_key`) so they aren't duplicated here.
    """
    return {"bronze_key": bronze_key}
