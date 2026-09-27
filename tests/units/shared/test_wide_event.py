import json
from dataclasses import dataclass

import pytest

from shared.wide_event import log_progress, wide_event


@dataclass
class _FakeContext:
    function_name: str = "capitol-lake-house-collect"
    function_version: str = "$LATEST"
    aws_request_id: str = "req-123"


def _logged_event(caplog):
    assert len(caplog.records) == 1
    return json.loads(caplog.records[0].message)


def test_emits_one_json_event_with_business_fields(caplog):
    with caplog.at_level("INFO", logger="capitol_lake"):
        with wide_event("house_collect", _FakeContext()) as log:
            log["year"] = 2024
            log["written_count"] = 3

    event = _logged_event(caplog)
    assert event["stage"] == "house_collect"
    assert event["year"] == 2024
    assert event["written_count"] == 3
    assert event["outcome"] == "success"
    assert isinstance(event["duration_ms"], int | float)


def test_includes_lambda_context_and_region(caplog, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    with caplog.at_level("INFO", logger="capitol_lake"):
        with wide_event("extract", _FakeContext(aws_request_id="req-456")):
            pass

    event = _logged_event(caplog)
    assert event["function_name"] == "capitol-lake-house-collect"
    assert event["aws_request_id"] == "req-456"
    assert event["region"] == "us-east-1"


def test_logs_error_outcome_and_reraises(caplog):
    with caplog.at_level("INFO", logger="capitol_lake"):
        with pytest.raises(ValueError, match="boom"):
            with wide_event("extract", _FakeContext()) as log:
                log["record_count"] = 1
                raise ValueError("boom")

    event = _logged_event(caplog)
    assert event["outcome"] == "error"
    assert event["error"] == {"type": "ValueError", "message": "boom"}
    assert event["record_count"] == 1
    assert caplog.records[0].levelname == "ERROR"


def test_log_progress_emits_immediately_with_business_fields(caplog):
    with caplog.at_level("INFO", logger="capitol_lake"):
        log_progress("house_collect", _FakeContext(), index=3, total=10, doc_id="20012345")

    event = _logged_event(caplog)
    assert event["stage"] == "house_collect"
    assert event["type"] == "progress"
    assert event["index"] == 3
    assert event["total"] == 10
    assert event["doc_id"] == "20012345"
    assert event["function_name"] == "capitol-lake-house-collect"


def test_log_progress_does_not_wait_for_wide_event_to_close(caplog):
    with caplog.at_level("INFO", logger="capitol_lake"):
        with wide_event("house_collect", _FakeContext()):
            log_progress("house_collect", _FakeContext(), index=1, total=2)
            assert len(caplog.records) == 1

    assert len(caplog.records) == 2
