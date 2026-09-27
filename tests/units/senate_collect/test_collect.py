import hashlib
import json
from pathlib import Path

import pytest

from senate_collect.collect import collect_senate
from shared.senate_index import RateLimiter, senate_filing_url

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


def _load_sample():
    return json.loads((FIXTURES / "senate_search_sample.json").read_text())


class FakeStore:
    """In-memory stand-in for the bronze bucket, keyed like S3."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def read_existing_sha256(self, meta_key: str) -> str | None:
        raw = self.objects.get(meta_key)
        if raw is None:
            return None
        return json.loads(raw)["sha256"]

    def write_bytes(self, key: str, data: bytes) -> None:
        self.objects[key] = data


def _fetch_filing_from(bodies: dict[str, bytes]):
    def _fetch(url: str) -> bytes:
        return bodies[url]

    return _fetch


def _no_sleep_rate_limiter():
    return RateLimiter(min_interval=1.0, clock=lambda: 0.0, sleep=lambda _: None)


def test_collect_senate_writes_a_real_recorded_ptr_filing_byte_for_byte():
    """Round-trips an actual fetched `/ptr/` page (not synthetic bytes) through bronze_write.

    `senate_ptr_sample.html` is the real HTML `senate_filing_url` returned for
    `b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f` (captured 2026-09-23, via a
    headless-Chromium session that cleared the Akamai check — a plain HTTP
    client does not, even reusing that session's cookies). This closes the
    gap the House collector's tests don't have either: proof that a real
    filing's bytes, not just a synthetic stand-in, survive the bronze write
    unmodified.
    """
    response = _load_sample()
    id_1 = "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f"
    real_bytes = (FIXTURES / "senate_ptr_sample.html").read_bytes()
    store = FakeStore()

    result = collect_senate(
        response,
        fetch_filing=_fetch_filing_from(
            {
                senate_filing_url(id_1): real_bytes,
                senate_filing_url("fda235b3-bad7-4637-8fa1-053f354d929c"): b"<html>ptr two</html>",
            }
        ),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2026-09-23T00:00:00Z",
        rate_limiter=_no_sleep_rate_limiter(),
    )

    key = f"bronze/senate/year=2026/{id_1}.html"
    assert key in result["written"]
    assert store.objects[key] == real_bytes

    meta = json.loads(store.objects[key + ".meta.json"])
    assert meta["sha256"] == hashlib.sha256(real_bytes).hexdigest()
    assert meta["doc_id"] == id_1
    assert meta["chamber"] == "senate"
    assert meta["kind"] == "ptr"


def test_collect_senate_writes_new_ptr_filings_with_correct_keys_and_metadata():
    response = _load_sample()
    id_1 = "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f"
    id_2 = "fda235b3-bad7-4637-8fa1-053f354d929c"
    bodies = {
        senate_filing_url(id_1): b"<html>ptr filing one</html>",
        senate_filing_url(id_2): b"<html>ptr filing two</html>",
    }
    store = FakeStore()

    result = collect_senate(
        response,
        fetch_filing=_fetch_filing_from(bodies),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2026-09-23T00:00:00Z",
        rate_limiter=_no_sleep_rate_limiter(),
    )

    key_1 = f"bronze/senate/year=2026/{id_1}.html"
    key_2 = f"bronze/senate/year=2026/{id_2}.html"

    assert result == {"years": [2026], "written": [key_1, key_2], "noop": []}
    assert store.objects[key_1] == bodies[senate_filing_url(id_1)]

    meta = json.loads(store.objects[key_1 + ".meta.json"])
    assert meta["doc_id"] == id_1
    assert meta["chamber"] == "senate"
    assert meta["year"] == 2026
    assert meta["source_url"] == senate_filing_url(id_1)
    assert meta["kind"] == "ptr"
    assert meta["sha256"] == hashlib.sha256(bodies[senate_filing_url(id_1)]).hexdigest()


def test_collect_senate_never_fetches_non_ptr_filings():
    response = _load_sample()
    fetched_urls = []

    def _fetch(url: str) -> bytes:
        fetched_urls.append(url)
        return b"<html>ok</html>"

    store = FakeStore()

    collect_senate(
        response,
        fetch_filing=_fetch,
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2026-09-23T00:00:00Z",
        rate_limiter=_no_sleep_rate_limiter(),
    )

    assert fetched_urls == [
        senate_filing_url("b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f"),
        senate_filing_url("fda235b3-bad7-4637-8fa1-053f354d929c"),
    ]


def test_collect_senate_is_idempotent_on_unchanged_source():
    response = _load_sample()
    id_1 = "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f"
    id_2 = "fda235b3-bad7-4637-8fa1-053f354d929c"
    bodies = {
        senate_filing_url(id_1): b"<html>ptr filing one</html>",
        senate_filing_url(id_2): b"<html>ptr filing two</html>",
    }
    store = FakeStore()

    kwargs = dict(
        fetch_filing=_fetch_filing_from(bodies),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2026-09-23T00:00:00Z",
    )

    collect_senate(response, rate_limiter=_no_sleep_rate_limiter(), **kwargs)
    objects_after_first_run = dict(store.objects)

    result = collect_senate(response, rate_limiter=_no_sleep_rate_limiter(), **kwargs)

    assert result["written"] == []
    assert sorted(result["noop"]) == sorted(
        [f"bronze/senate/year=2026/{id_1}.html", f"bronze/senate/year=2026/{id_2}.html"]
    )
    assert store.objects == objects_after_first_run


def test_collect_senate_rate_limits_between_filing_fetches():
    response = _load_sample()
    id_1 = "b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f"
    id_2 = "fda235b3-bad7-4637-8fa1-053f354d929c"
    bodies = {
        senate_filing_url(id_1): b"one",
        senate_filing_url(id_2): b"two",
    }
    store = FakeStore()
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: 100.0, sleep=sleeps.append)

    collect_senate(
        response,
        fetch_filing=_fetch_filing_from(bodies),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2026-09-23T00:00:00Z",
        rate_limiter=limiter,
    )

    assert sleeps == [pytest.approx(1.0)]
