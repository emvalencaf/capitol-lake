"""Stage-to-stage handoff (#43): translate a Lambda event into bronze keys.

Per the orchestration shape settled in #18, stages are chained via SQS
carrying only S3-key references, never inline document bytes: a queue
message is `{"bronze_key": ...}`, built by `extract_queue_message` and sent
by an upstream handler (`house_collect/handler`). The Senate side has no
scheduled collector (#18); once its bronze objects land in S3 (manually or
via `senate_collect/handler`), an S3 event notification on the bronze bucket
forwards onto that same SQS queue (ADR-0015) rather than invoking the
downstream Lambda directly — this gives Senate-triggered messages the same
retry/DLQ handling House's own messages already got, at the cost of the SQS
record's `body` sometimes being a raw S3 event notification (itself a
`{"Records": [...]}` document) instead of `{"bronze_key": ...}`.
`bronze_key_records_from_event` unpacks whichever of three shapes a stage's
handler receives: a plain `{"bronze_key": ...}` invocation (manual/local/RIE
testing, matching every other handler's existing convention), an SQS event
(one or more records, each either House's own message shape or an
S3-notification-via-SQS envelope), or a direct S3 event (kept for any future
stage that still gets invoked that way) — kept here rather than duplicated
in every downstream handler.
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
    SQS event — whether the record's own body is House's `{"bronze_key":
    ...}` shape or a forwarded S3 event notification, both cases have a real
    SQS message behind them, so both get a retry/DLQ handle (a handler's own
    `batchItemFailures` entry, on that record's failure, per #43's
    per-message DLQ posture and ADR-0015) — or `None` otherwise: a plain
    invocation or a direct S3 event has no SQS message to retry/DLQ, so a
    handler must never report a batch-item failure for one of those, even in
    a batch that mixes sources.
    """

    bronze_key: str
    message_id: str | None


def _bronze_key_records_from_sqs(record: dict) -> list[BronzeKeyRecord]:
    body = json.loads(record["body"])
    message_id = record["messageId"]

    if "bronze_key" in body:
        return [BronzeKeyRecord(body["bronze_key"], message_id)]
    if "Records" in body:
        # S3 delivered its event notification through this SQS queue instead
        # of invoking the stage directly (ADR-0015, e.g. Senate's bronze
        # writes) — every nested S3 record shares this outer SQS record's
        # retry/DLQ handle, since a redelivery of this one message is what a
        # failure here would actually retry.
        return [
            BronzeKeyRecord(unquote_plus(nested["s3"]["object"]["key"]), message_id)
            for nested in body["Records"]
        ]
    raise UnrecognizedEventShapeError(f"unrecognized SQS message body shape: {sorted(body)}")


def _bronze_key_records_from_s3(record: dict) -> list[BronzeKeyRecord]:
    return [BronzeKeyRecord(unquote_plus(record["s3"]["object"]["key"]), None)]


_RECORD_PARSERS = {"aws:sqs": _bronze_key_records_from_sqs, "aws:s3": _bronze_key_records_from_s3}


def bronze_key_records_from_event(event: dict) -> list[BronzeKeyRecord]:
    """Extract every bronze key (with its retry handle) an event carries, in order.

    Dispatches on shape: a plain `{"bronze_key": ...}` invocation yields
    that one key with no `message_id`; an event with `Records` unpacks each
    record by its `eventSource` — an SQS record's body is either House's own
    `{"bronze_key": ...}` shape or a forwarded S3 notification (both keyed
    with that record's `messageId`, see `_bronze_key_records_from_sqs`), a
    direct S3 record is its own `s3.object.key` (URL-decoded since S3 event
    keys are `application/x-www-form-urlencoded`) with no `message_id` — a
    batch can mix record sources, and one SQS record can now yield more than
    one bronze key, both of which a handler's failure reporting must handle
    safely (see `BronzeKeyRecord`). Raises `UnrecognizedEventShapeError` for
    anything else, rather than silently skipping a record a future event
    source doesn't yet match.
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
