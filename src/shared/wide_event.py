"""One structured JSON log line per Lambda invocation (canonical log line /
wide event, `.claude/skills/logging-best-practices`), instead of scattered
`print()`/`logging` calls through a handler.

`wide_event()` is a context manager every handler wraps its body in. It
yields a plain `dict` the handler fills with business context (record
counts, a `year`, a `bronze_key`, ...); this module only owns the fields
every stage must agree on regardless of what the handler does: which stage
ran, the Lambda's own identity (`aws_request_id`/`function_name`/
`function_version`/AWS region — no commit hash yet, since nothing currently
tags a deployed image with one; see CHANGELOG), how long it took, and
whether it raised.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

_logger = logging.getLogger("capitol_lake")
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.propagate = False
_logger.setLevel(logging.INFO)


def _environment(context: object) -> dict:
    return {
        "function_name": getattr(context, "function_name", None),
        "function_version": getattr(context, "function_version", None),
        "aws_request_id": getattr(context, "aws_request_id", None),
        "region": os.environ.get("AWS_REGION"),
    }


def log_progress(stage: str, context: object, **fields: object) -> None:
    """Emit one JSON log line immediately, unlike `wide_event`'s end-of-run summary.

    Pair with a long-running loop (a full-year House backfill, ~500 filings
    at ~1 req/s can run close to the Lambda's 900s timeout) so CloudWatch
    shows activity throughout an invocation instead of staying silent until
    the single event `wide_event` logs at the very end — which otherwise
    looks indistinguishable from a hung handler.
    """
    event = {"stage": stage, "type": "progress", **_environment(context), **fields}
    _logger.info(json.dumps(event, default=str))


@contextmanager
def wide_event(stage: str, context: object) -> Iterator[dict]:
    """Emit exactly one JSON log line for this invocation, success or not.

    Yields the event `dict` so the handler can add business fields as it
    goes (`log["written_count"] = len(result["written"])`). `outcome`,
    `duration_ms`, and — on an exception — `error` are always set here, and
    the exception is re-raised unchanged after the event is logged.
    """
    event: dict = {"stage": stage, **_environment(context)}
    start = time.monotonic()
    try:
        yield event
    except Exception as exc:
        event["outcome"] = "error"
        event["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    else:
        event.setdefault("outcome", "success")
    finally:
        event["duration_ms"] = round((time.monotonic() - start) * 1000, 1)
        log = _logger.error if event.get("outcome") == "error" else _logger.info
        log(json.dumps(event, default=str))
