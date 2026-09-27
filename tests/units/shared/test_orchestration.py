import json

import pytest

from shared.orchestration import (
    BronzeKeyRecord,
    UnrecognizedEventShapeError,
    bronze_key_records_from_event,
    bronze_keys_from_event,
    extract_queue_message,
)


def test_bronze_keys_from_plain_invocation_event():
    event = {"bronze_key": "bronze/house/year=2024/20012345.pdf"}

    assert bronze_keys_from_event(event) == ["bronze/house/year=2024/20012345.pdf"]


def test_bronze_keys_from_sqs_event_parses_each_record_body():
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "eventSource": "aws:sqs",
                "body": json.dumps({"bronze_key": "bronze/house/year=2024/20012345.pdf"}),
            },
            {
                "messageId": "msg-2",
                "eventSource": "aws:sqs",
                "body": json.dumps({"bronze_key": "bronze/house/year=2024/20012346.pdf"}),
            },
        ]
    }

    assert bronze_keys_from_event(event) == [
        "bronze/house/year=2024/20012345.pdf",
        "bronze/house/year=2024/20012346.pdf",
    ]


def test_bronze_keys_from_s3_event_unquotes_the_object_key():
    event = {
        "Records": [
            {
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": {"name": "bronze"},
                    "object": {"key": "senate/year=2024/a1b2%2Bc3.html"},
                },
            }
        ]
    }

    assert bronze_keys_from_event(event) == ["senate/year=2024/a1b2+c3.html"]


def test_bronze_keys_from_mixed_sqs_and_s3_records():
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "eventSource": "aws:sqs",
                "body": json.dumps({"bronze_key": "bronze/house/year=2024/20012345.pdf"}),
            },
            {
                "eventSource": "aws:s3",
                "s3": {"object": {"key": "bronze/senate/year=2024/abc123.html"}},
            },
        ]
    }

    assert bronze_keys_from_event(event) == [
        "bronze/house/year=2024/20012345.pdf",
        "bronze/senate/year=2024/abc123.html",
    ]


def test_bronze_keys_from_event_rejects_unknown_shape():
    with pytest.raises(UnrecognizedEventShapeError):
        bronze_keys_from_event({"Records": [{"eventSource": "aws:sns"}]})

    with pytest.raises(UnrecognizedEventShapeError):
        bronze_keys_from_event({"nothing": "recognizable"})


def test_bronze_key_records_pair_sqs_records_with_their_message_id():
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "eventSource": "aws:sqs",
                "body": json.dumps({"bronze_key": "bronze/house/year=2024/20012345.pdf"}),
            }
        ]
    }

    assert bronze_key_records_from_event(event) == [
        BronzeKeyRecord("bronze/house/year=2024/20012345.pdf", "msg-1")
    ]


def test_bronze_key_records_give_no_message_id_for_s3_or_plain_records():
    s3_event = {
        "Records": [{"eventSource": "aws:s3", "s3": {"object": {"key": "bronze/senate/x.html"}}}]
    }
    plain_event = {"bronze_key": "bronze/house/year=2024/20012345.pdf"}

    assert bronze_key_records_from_event(s3_event) == [
        BronzeKeyRecord("bronze/senate/x.html", None)
    ]
    assert bronze_key_records_from_event(plain_event) == [
        BronzeKeyRecord("bronze/house/year=2024/20012345.pdf", None)
    ]


def test_bronze_key_records_from_a_mixed_batch_only_carry_the_sqs_records_message_id():
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "eventSource": "aws:sqs",
                "body": json.dumps({"bronze_key": "bronze/house/year=2024/20012345.pdf"}),
            },
            {"eventSource": "aws:s3", "s3": {"object": {"key": "bronze/senate/x.html"}}},
        ]
    }

    assert bronze_key_records_from_event(event) == [
        BronzeKeyRecord("bronze/house/year=2024/20012345.pdf", "msg-1"),
        BronzeKeyRecord("bronze/senate/x.html", None),
    ]


def test_bronze_keys_from_sqs_rejects_forwarded_s3_notification_shape():
    """ADR-0015's S3-notification-via-SQS envelope is gone (ADR-0016): every
    collector enqueues its own `{"bronze_key": ...}` message directly now,
    so a nested `{"Records": [...]}` body is no longer a recognized shape.
    """
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "eventSource": "aws:sqs",
                "body": json.dumps(
                    {
                        "Records": [
                            {
                                "eventSource": "aws:s3",
                                "s3": {"object": {"key": "bronze/senate/year=2024/abc123.html"}},
                            }
                        ]
                    }
                ),
            }
        ]
    }

    with pytest.raises(UnrecognizedEventShapeError):
        bronze_keys_from_event(event)


def test_bronze_keys_from_sqs_rejects_unrecognized_message_body_shape():
    event = {
        "Records": [
            {
                "messageId": "msg-1",
                "eventSource": "aws:sqs",
                "body": json.dumps({"nothing": "recognizable"}),
            }
        ]
    }

    with pytest.raises(UnrecognizedEventShapeError):
        bronze_keys_from_event(event)


def test_extract_queue_message_carries_only_the_bronze_key():
    assert extract_queue_message("bronze/house/year=2024/20012345.pdf") == {
        "bronze_key": "bronze/house/year=2024/20012345.pdf"
    }
