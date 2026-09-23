import hashlib
import json

import pytest

from capitol_lake.stages.senate_collect import (
    PAPER_FILING_KIND,
    PTR_FILING_KIND,
    RateLimiter,
    UnknownFilingKindError,
    collect_senate,
    parse_senate_index,
    route_filing_kind,
    senate_filing_url,
)

# ---------------------------------------------------------------------------
# route_filing_kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("ptr", PTR_FILING_KIND),
        ("PTR", PTR_FILING_KIND),
        (" ptr ", PTR_FILING_KIND),
        ("paper", PAPER_FILING_KIND),
        ("PAPER", PAPER_FILING_KIND),
    ],
)
def test_route_filing_kind_classifies_known_kinds(raw, kind):
    assert route_filing_kind(raw) == kind


def test_route_filing_kind_raises_on_unknown_kind():
    with pytest.raises(UnknownFilingKindError):
        route_filing_kind("annual")


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def test_senate_filing_url_includes_filing_id_and_ptr_path():
    url = senate_filing_url("3b1f6a2e-1111-2222-3333-444455556666")
    assert "/ptr/" in url
    assert url.endswith("3b1f6a2e-1111-2222-3333-444455556666/")


# ---------------------------------------------------------------------------
# parse_senate_index
# ---------------------------------------------------------------------------


def test_parse_senate_index_keeps_only_ptr_rows():
    rows = [
        {"filing_id": "uuid-1", "filing_type": "ptr"},
        {"filing_id": "uuid-2", "filing_type": "paper"},
        {"filing_id": "uuid-3", "filing_type": "ptr"},
    ]

    entries = parse_senate_index(rows, 2024)

    assert [(e.filing_id, e.kind, e.index_row) for e in entries] == [
        ("uuid-1", "ptr", 0),
        ("uuid-3", "ptr", 2),
    ]
    assert all(e.year == 2024 for e in entries)


def test_parse_senate_index_skips_unrecognized_filing_types():
    rows = [
        {"filing_id": "uuid-1", "filing_type": "annual"},
        {"filing_id": "uuid-2", "filing_type": "ptr"},
    ]

    entries = parse_senate_index(rows, 2024)

    assert [e.filing_id for e in entries] == ["uuid-2"]


def test_parse_senate_index_skips_rows_without_filing_id():
    rows = [
        {"filing_id": "", "filing_type": "ptr"},
        {"filing_id": "uuid-2", "filing_type": "ptr"},
    ]

    entries = parse_senate_index(rows, 2024)

    assert [e.filing_id for e in entries] == ["uuid-2"]


# ---------------------------------------------------------------------------
# RateLimiter (shared shape with the House collector; behavior re-verified here
# since senate_collect owns its own instance)
# ---------------------------------------------------------------------------


def test_rate_limiter_does_not_sleep_on_first_call():
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: 100.0, sleep=sleeps.append)

    limiter.wait()

    assert sleeps == []


def test_rate_limiter_sleeps_remaining_interval_on_fast_second_call():
    clock_values = iter([100.0, 100.2, 100.2])
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: next(clock_values), sleep=sleeps.append)

    limiter.wait()
    limiter.wait()

    assert sleeps == [pytest.approx(0.8)]


# ---------------------------------------------------------------------------
# collect_senate (fake network + storage, exercises the full loop)
# ---------------------------------------------------------------------------


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


def test_collect_senate_writes_new_ptr_filings_with_correct_keys_and_metadata():
    filing_id = "3b1f6a2e-1111-2222-3333-444455556666"
    rows = [{"filing_id": filing_id, "filing_type": "ptr"}]
    filing_bytes = b"<html>fake senate ptr filing</html>"
    url = senate_filing_url(filing_id)
    store = FakeStore()

    result = collect_senate(
        2024,
        rows,
        fetch_filing=_fetch_filing_from({url: filing_bytes}),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
        rate_limiter=_no_sleep_rate_limiter(),
    )

    bronze_key = f"bronze/senate/year=2024/{filing_id}.html"
    meta_key = bronze_key + ".meta.json"

    assert result == {"year": 2024, "written": [bronze_key], "noop": []}
    assert store.objects[bronze_key] == filing_bytes

    meta = json.loads(store.objects[meta_key])
    assert meta["doc_id"] == filing_id
    assert meta["chamber"] == "senate"
    assert meta["year"] == 2024
    assert meta["source_url"] == url
    assert meta["kind"] == "ptr"
    assert meta["sha256"] == hashlib.sha256(filing_bytes).hexdigest()


def test_collect_senate_never_fetches_paper_filings():
    rows = [
        {"filing_id": "uuid-ptr", "filing_type": "ptr"},
        {"filing_id": "uuid-paper", "filing_type": "paper"},
    ]
    fetched_urls = []

    def _fetch(url: str) -> bytes:
        fetched_urls.append(url)
        return b"<html>ok</html>"

    store = FakeStore()

    collect_senate(
        2024,
        rows,
        fetch_filing=_fetch,
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
        rate_limiter=_no_sleep_rate_limiter(),
    )

    assert fetched_urls == [senate_filing_url("uuid-ptr")]


def test_collect_senate_treats_amendment_uuid_as_a_new_filing_not_a_version():
    original_id = "3b1f6a2e-1111-2222-3333-444455556666"
    amendment_id = "9a8b7c6d-9999-8888-7777-666655554444"
    rows = [
        {"filing_id": original_id, "filing_type": "ptr"},
        {"filing_id": amendment_id, "filing_type": "ptr"},
    ]
    bodies = {
        senate_filing_url(original_id): b"<html>original</html>",
        senate_filing_url(amendment_id): b"<html>amendment</html>",
    }
    store = FakeStore()

    result = collect_senate(
        2024,
        rows,
        fetch_filing=_fetch_filing_from(bodies),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
        rate_limiter=_no_sleep_rate_limiter(),
    )

    assert result["written"] == [
        f"bronze/senate/year=2024/{original_id}.html",
        f"bronze/senate/year=2024/{amendment_id}.html",
    ]
    assert result["noop"] == []


def test_collect_senate_is_idempotent_on_unchanged_source():
    filing_id = "3b1f6a2e-1111-2222-3333-444455556666"
    rows = [{"filing_id": filing_id, "filing_type": "ptr"}]
    filing_bytes = b"<html>fake senate ptr filing</html>"
    url = senate_filing_url(filing_id)
    store = FakeStore()

    kwargs = dict(
        fetch_filing=_fetch_filing_from({url: filing_bytes}),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
    )

    collect_senate(2024, rows, rate_limiter=_no_sleep_rate_limiter(), **kwargs)
    objects_after_first_run = dict(store.objects)

    result = collect_senate(2024, rows, rate_limiter=_no_sleep_rate_limiter(), **kwargs)

    assert result["written"] == []
    assert result["noop"] == [f"bronze/senate/year=2024/{filing_id}.html"]
    assert store.objects == objects_after_first_run


def test_collect_senate_rate_limits_between_filing_fetches():
    rows = [
        {"filing_id": "uuid-1", "filing_type": "ptr"},
        {"filing_id": "uuid-2", "filing_type": "ptr"},
    ]
    bodies = {
        senate_filing_url("uuid-1"): b"<html>one</html>",
        senate_filing_url("uuid-2"): b"<html>two</html>",
    }
    store = FakeStore()
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: 100.0, sleep=sleeps.append)

    collect_senate(
        2024,
        rows,
        fetch_filing=_fetch_filing_from(bodies),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
        rate_limiter=limiter,
    )

    assert sleeps == [pytest.approx(1.0)]
