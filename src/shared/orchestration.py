"""Stage-to-stage handoff (#43): translate a Lambda event into bronze keys.

Per the orchestration shape settled in #18, stages are chained via SQS
carrying only S3-key references, never inline document bytes: a queue
message is `{"bronze_key": ...}`, built by `extract_queue_message` and sent
by every upstream collector's own handler (`house_collect`, `senate_collect`,
`senate_collect_automated` — ADR-0016). Senate previously had no scheduled
collector of its own SQS-sending code and instead relied on an S3 event
notification on the bronze bucket forwarding onto extract's queue
(ADR-0015); that bridge is gone now that every collector enqueues its own
writes directly, so an SQS record's `body` is always `{"bronze_key": ...}`.
`bronze_key_records_from_event` unpacks whichever of two shapes a stage's
handler receives: a plain `{"bronze_key": ...}` invocation (manual/local/RIE
testing, matching every other handler's existing convention), or an SQS
event (one or more records, each `{"bronze_key": ...}`) — kept here rather
than duplicated in every downstream handler. A direct S3 event
(`eventSource == "aws:s3"`) is still supported for any future stage invoked
that way, though nothing in this stack produces one today.
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
    SQS event — a real SQS message behind it means a retry/DLQ handle (a
    handler's own `batchItemFailures` entry, on that record's failure, per
    #43's per-message DLQ posture) — or `None` otherwise: a plain invocation
    or a direct S3 event has no SQS message to retry/DLQ, so a handler must
    never report a batch-item failure for one of those, even in a batch that
    mixes sources.
    """

    bronze_key: str
    message_id: str | None


def _bronze_key_records_from_sqs(record: dict) -> list[BronzeKeyRecord]:
    body = json.loads(record["body"])
    message_id = record["messageId"]

    if "bronze_key" in body:
        return [BronzeKeyRecord(body["bronze_key"], message_id)]
    raise UnrecognizedEventShapeError(f"unrecognized SQS message body shape: {sorted(body)}")


def _bronze_key_records_from_s3(record: dict) -> list[BronzeKeyRecord]:
    return [BronzeKeyRecord(unquote_plus(record["s3"]["object"]["key"]), None)]


_RECORD_PARSERS = {"aws:sqs": _bronze_key_records_from_sqs, "aws:s3": _bronze_key_records_from_s3}


def bronze_key_records_from_event(event: dict) -> list[BronzeKeyRecord]:
    """Extract every bronze key (with its retry handle) an event carries, in order.

    Dispatches on shape: a plain `{"bronze_key": ...}` invocation yields
    that one key with no `message_id`; an event with `Records` unpacks each
    record by its `eventSource` — an SQS record's body is `{"bronze_key":
    ...}` (keyed with that record's `messageId`, see
    `_bronze_key_records_from_sqs`), a direct S3 record is its own
    `s3.object.key` (URL-decoded since S3 event keys are
    `application/x-www-form-urlencoded`) with no `message_id` — a batch can
    mix record sources (see `BronzeKeyRecord`). Raises
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
            records.extend(parser(record))
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
