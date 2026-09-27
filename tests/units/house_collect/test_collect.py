import hashlib
import json
import zipfile
from io import BytesIO

import pytest

from house_collect.collect import (
    RateLimiter,
    collect_house,
    house_filing_url,
    house_index_url,
    parse_house_index,
)

INDEX_XML_TEMPLATE = """<?xml version="1.0"?>
<FinancialDisclosure>
{rows}
</FinancialDisclosure>
"""

ROW_TEMPLATE = """
<Member>
    <Last>Doe</Last>
    <FilingType>{filing_type}</FilingType>
    <StateDst>WA00</StateDst>
    <Year>{year}</Year>
    <FilingDate>{year}-05-01</FilingDate>
    <DocID>{doc_id}</DocID>
</Member>
"""


def _index_zip(rows: list[dict], year: int) -> bytes:
    xml = INDEX_XML_TEMPLATE.format(
        rows="".join(ROW_TEMPLATE.format(year=year, **row) for row in rows)
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{year}FD.xml", xml)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def test_house_index_url_includes_year():
    assert house_index_url(2024).endswith("2024FD.zip")


def test_house_filing_url_includes_year_and_doc_id():
    url = house_filing_url("20012345", 2024)
    assert "2024" in url
    assert url.endswith("20012345.pdf")


# ---------------------------------------------------------------------------
# parse_house_index
# ---------------------------------------------------------------------------


def test_parse_house_index_routes_digital_and_scanned():
    zip_bytes = _index_zip(
        [
            {"filing_type": "P", "doc_id": "20012345"},
            {"filing_type": "P", "doc_id": "8212345"},
        ],
        year=2024,
    )

    entries = parse_house_index(zip_bytes, 2024)

    assert [(e.doc_id, e.kind, e.index_row) for e in entries] == [
        ("20012345", "digital", 0),
        ("8212345", "scanned", 1),
    ]
    assert all(e.year == 2024 for e in entries)


def test_parse_house_index_skips_non_ptr_filing_types():
    zip_bytes = _index_zip(
        [
            {"filing_type": "A", "doc_id": "20012345"},
            {"filing_type": "P", "doc_id": "20099999"},
        ],
        year=2024,
    )

    entries = parse_house_index(zip_bytes, 2024)

    assert [e.doc_id for e in entries] == ["20099999"]


def test_parse_house_index_skips_unrecognized_doc_id_prefix():
    zip_bytes = _index_zip(
        [
            {"filing_type": "P", "doc_id": "77012345"},
            {"filing_type": "P", "doc_id": "20099999"},
        ],
        year=2024,
    )

    entries = parse_house_index(zip_bytes, 2024)

    assert [e.doc_id for e in entries] == ["20099999"]


def test_parse_house_index_raises_without_xml_member():
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "not xml")

    with pytest.raises(ValueError, match="no XML member"):
        parse_house_index(buf.getvalue(), 2024)


# ---------------------------------------------------------------------------
# RateLimiter
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


def test_rate_limiter_does_not_sleep_when_interval_already_elapsed():
    clock_values = iter([100.0, 101.5])
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: next(clock_values), sleep=sleeps.append)

    limiter.wait()
    limiter.wait()

    assert sleeps == []


# ---------------------------------------------------------------------------
# collect_house (fake network + storage, exercises the full loop)
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


def _fetch_index_returning(zip_bytes: bytes):
    return lambda url: zip_bytes


def _fetch_filing_from(bodies: dict[str, bytes]):
    def _fetch(url: str) -> bytes:
        return bodies[url]

    return _fetch


def _no_sleep_rate_limiter():
    return RateLimiter(min_interval=1.0, clock=lambda: 0.0, sleep=lambda _: None)


def test_collect_house_writes_new_filings_with_correct_keys_and_metadata():
    zip_bytes = _index_zip(
        [{"filing_type": "P", "doc_id": "20012345"}],
        year=2024,
    )
    filing_bytes = b"%PDF-1.4 fake pdf bytes"
    url = house_filing_url("20012345", 2024)
    store = FakeStore()

    result = collect_house(
        2024,
        fetch_index=_fetch_index_returning(zip_bytes),
        fetch_filing=_fetch_filing_from({url: filing_bytes}),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
        rate_limiter=_no_sleep_rate_limiter(),
    )

    bronze_key = "bronze/house/year=2024/20012345.pdf"
    meta_key = bronze_key + ".meta.json"

    assert result == {"year": 2024, "written": [bronze_key], "noop": []}
    assert store.objects[bronze_key] == filing_bytes

    meta = json.loads(store.objects[meta_key])
    assert meta["doc_id"] == "20012345"
    assert meta["chamber"] == "house"
    assert meta["year"] == 2024
    assert meta["source_url"] == url
    assert meta["kind"] == "digital"
    assert meta["sha256"] == hashlib.sha256(filing_bytes).hexdigest()


def test_collect_house_is_idempotent_on_unchanged_source():
    zip_bytes = _index_zip(
        [{"filing_type": "P", "doc_id": "20012345"}],
        year=2024,
    )
    filing_bytes = b"%PDF-1.4 fake pdf bytes"
    url = house_filing_url("20012345", 2024)
    store = FakeStore()

    kwargs = dict(
        fetch_index=_fetch_index_returning(zip_bytes),
        fetch_filing=_fetch_filing_from({url: filing_bytes}),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
    )

    collect_house(2024, rate_limiter=_no_sleep_rate_limiter(), **kwargs)
    objects_after_first_run = dict(store.objects)

    result = collect_house(2024, rate_limiter=_no_sleep_rate_limiter(), **kwargs)

    assert result["written"] == []
    assert result["noop"] == ["bronze/house/year=2024/20012345.pdf"]
    assert store.objects == objects_after_first_run


def test_collect_house_rate_limits_between_filing_fetches():
    zip_bytes = _index_zip(
        [
            {"filing_type": "P", "doc_id": "20011111"},
            {"filing_type": "P", "doc_id": "20022222"},
        ],
        year=2024,
    )
    bodies = {
        house_filing_url("20011111", 2024): b"one",
        house_filing_url("20022222", 2024): b"two",
    }
    store = FakeStore()
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: 100.0, sleep=sleeps.append)

    collect_house(
        2024,
        fetch_index=_fetch_index_returning(zip_bytes),
        fetch_filing=_fetch_filing_from(bodies),
        read_existing_sha256=store.read_existing_sha256,
        write_bytes=store.write_bytes,
        now=lambda: "2024-06-01T00:00:00Z",
        rate_limiter=limiter,
    )

    assert sleeps == [pytest.approx(1.0)]
