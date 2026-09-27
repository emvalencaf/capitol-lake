"""Full-document LLM extractor (#89): schema shape, per-row coercion, and page routing.

`complete_text`/`complete_vision` are always canned/injected here, per this
codebase's convention for network dependencies (`test_llm_fallback.py`): the
stage's decision logic is exercised against fixed responses, never a real
provider call. Real fixtures (`tests/fixtures/house_digital_*.pdf`,
`house_scanned_*.pdf`) are reused so page counts and OCR/rasterization
behavior match what `extract_digital`/`extract_scanned` are themselves
tested against.
"""

from datetime import date
from pathlib import Path

import pytest

from extract_data.evaluation import SCORED_FIELDS
from extract_data.llm_extract import (
    EXTRACTOR_NAME,
    LLM_CONFIDENCE,
    build_transaction,
    extract_llm,
    page_schema,
    transaction_schema,
)
from shared.llm_providers import Provider
from shared.schema import AssetType, Chamber, Filing, Owner, Provenance, TransactionType

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

FILING = Filing(
    doc_id="1",
    chamber=Chamber.HOUSE,
    filer_name="placeholder",
    filing_date=date(2025, 1, 1),
    year=2025,
    confidence=LLM_CONFIDENCE,
    provenance=Provenance(bronze_key="bronze/house/year=2025/1.pdf", extractor=EXTRACTOR_NAME),
)

VALID_ROW = {
    "owner": "self",
    "transaction_type": "purchase",
    "asset_type": "stock",
    "asset_description": "Apple Inc.",
    "transaction_date": "2025-01-15",
    "notification_date": "2025-01-16",
    "value_min": 1001,
    "value_max": 15000,
    "filing_status": "New",
    "sub_owner": None,
    "description": None,
}


class _FakeProvider:
    """Records every call and returns a fixed page response, per `Provider`'s contract."""

    def __init__(self, response: dict):
        self.response = response
        self.text_calls: list[tuple] = []
        self.vision_calls: list[tuple] = []

    def complete_text(self, prompt, source_text, schema):
        self.text_calls.append((prompt, source_text, schema))
        return self.response

    def complete_vision(self, prompt, page_image, schema):
        self.vision_calls.append((prompt, page_image, schema))
        return self.response

    def as_provider(self) -> Provider:
        return Provider("fake", self.complete_text, self.complete_vision)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_transaction_schema_covers_every_scored_field():
    schema = transaction_schema()

    assert set(schema["properties"]) == set(SCORED_FIELDS)
    assert set(schema["required"]) == set(SCORED_FIELDS)
    assert schema["additionalProperties"] is False


def test_page_schema_wraps_transaction_schema_in_a_list():
    schema = page_schema()

    assert schema["required"] == ["transactions"]
    assert schema["properties"]["transactions"]["items"] == transaction_schema()


# ---------------------------------------------------------------------------
# build_transaction
# ---------------------------------------------------------------------------


def test_build_transaction_from_a_complete_row():
    transaction = build_transaction(VALID_ROW, FILING, line_no=1)

    assert transaction is not None
    assert transaction.line_no == 1
    assert transaction.owner is Owner.SELF
    assert transaction.transaction_type is TransactionType.PURCHASE
    assert transaction.asset_type is AssetType.STOCK
    assert transaction.asset_description == "Apple Inc."
    assert transaction.transaction_date == date(2025, 1, 15)
    assert transaction.notification_date == date(2025, 1, 16)
    assert transaction.value_range.min == 1001
    assert transaction.value_range.max == 15000
    assert transaction.confidence == LLM_CONFIDENCE
    assert transaction.field_confidence["owner"] == LLM_CONFIDENCE


def test_build_transaction_drops_row_with_no_transaction_date():
    row = {**VALID_ROW, "transaction_date": None}

    assert build_transaction(row, FILING, line_no=1) is None


def test_build_transaction_drops_row_with_no_asset_description():
    row = {**VALID_ROW, "asset_description": None}

    assert build_transaction(row, FILING, line_no=1) is None


def test_build_transaction_drops_row_with_an_invalid_enum_value():
    row = {**VALID_ROW, "owner": "not-a-real-owner"}

    assert build_transaction(row, FILING, line_no=1) is None


def test_build_transaction_defaults_null_owner_and_asset_type():
    row = {**VALID_ROW, "owner": None, "asset_type": None}

    transaction = build_transaction(row, FILING, line_no=1)

    assert transaction.owner is Owner.SELF
    assert transaction.asset_type is AssetType.OTHER


def test_build_transaction_leaves_value_range_null_when_value_min_is_null():
    row = {**VALID_ROW, "value_min": None, "value_max": None}

    transaction = build_transaction(row, FILING, line_no=1)

    assert transaction.value_range is None


# ---------------------------------------------------------------------------
# extract_llm: digital filing always uses complete_text
# ---------------------------------------------------------------------------


def test_extract_llm_digital_filing_calls_complete_text_once_per_page():
    fake = _FakeProvider({"transactions": [VALID_ROW, VALID_ROW]})
    pdf_bytes = (FIXTURES / "house_digital_20019582.pdf").read_bytes()

    result = extract_llm(
        pdf_bytes,
        bronze_key="bronze/house/year=2025/20019582.pdf",
        provider=fake.as_provider(),
        input_mode="vision",  # ignored for a digital filing
    )

    assert fake.vision_calls == []
    assert len(fake.text_calls) > 0
    assert result.filing.doc_id == "20019582"
    # Two transactions per page, renumbered sequentially across all pages.
    assert [t.line_no for t in result.transactions] == list(range(1, len(result.transactions) + 1))
    assert len(result.transactions) == 2 * len(fake.text_calls)


# ---------------------------------------------------------------------------
# extract_llm: scanned filing routes on input_mode
# ---------------------------------------------------------------------------


def test_extract_llm_scanned_filing_text_mode_uses_ocr_text():
    fake = _FakeProvider({"transactions": [VALID_ROW]})
    pdf_bytes = (FIXTURES / "house_scanned_8217884.pdf").read_bytes()

    result = extract_llm(
        pdf_bytes,
        bronze_key="bronze/house/year=2021/8217884.pdf",
        provider=fake.as_provider(),
        input_mode="text",
    )

    assert fake.vision_calls == []
    assert len(fake.text_calls) > 0
    # OCR text was actually passed, not empty pypdf text (a scanned PDF has none).
    assert all(isinstance(call[1], str) for call in fake.text_calls)
    assert result.filing.doc_id == "8217884"
    assert len(result.transactions) == len(fake.text_calls)


def test_extract_llm_scanned_filing_vision_mode_uses_page_images():
    fake = _FakeProvider({"transactions": [VALID_ROW]})
    pdf_bytes = (FIXTURES / "house_scanned_8217884.pdf").read_bytes()

    result = extract_llm(
        pdf_bytes,
        bronze_key="bronze/house/year=2021/8217884.pdf",
        provider=fake.as_provider(),
        input_mode="vision",
    )

    assert fake.text_calls == []
    assert len(fake.vision_calls) > 0
    assert all(isinstance(call[1], bytes) for call in fake.vision_calls)
    assert len(result.transactions) == len(fake.vision_calls)


def test_extract_llm_drops_unusable_rows_from_the_response():
    fake = _FakeProvider({"transactions": [VALID_ROW, {**VALID_ROW, "transaction_date": None}]})
    pdf_bytes = (FIXTURES / "house_digital_20019582.pdf").read_bytes()

    result = extract_llm(
        pdf_bytes, bronze_key="bronze/house/year=2025/20019582.pdf", provider=fake.as_provider()
    )

    # Every page returned one usable row and one unusable row: only the
    # usable ones survive, renumbered contiguously.
    assert len(result.transactions) == len(fake.text_calls)
    assert [t.line_no for t in result.transactions] == list(range(1, len(result.transactions) + 1))


def test_extract_llm_provider_failure_propagates(monkeypatch):
    def raising_complete_text(prompt, source_text, schema):
        raise RuntimeError("rate limited")

    provider = Provider("fake", raising_complete_text, raising_complete_text)
    pdf_bytes = (FIXTURES / "house_digital_20019582.pdf").read_bytes()

    with pytest.raises(RuntimeError, match="rate limited"):
        extract_llm(pdf_bytes, bronze_key="bronze/house/year=2025/20019582.pdf", provider=provider)
