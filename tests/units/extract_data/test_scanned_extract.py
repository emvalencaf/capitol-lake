"""Scanned House PDF extractor, exercised against real sampled House PTRs.

Both fixtures are unmodified scanned House PTR PDFs (no text layer) fetched
from `disclosures-clerk.house.gov`. `house_scanned_8217884.pdf` is clean
enough to extract fully; `house_scanned_8218417.pdf` is real scan noise the
extractor cannot honestly read a filer name or filing date from, and it
documents the resulting failure rather than a guessed row (ADR 0002).
"""

from datetime import date
from functools import cache
from pathlib import Path

import pytest

from extract_data.scanned_extract import EXTRACTOR_NAME, FULL_CONFIDENCE, extract_scanned
from shared.schema import AssetType, Chamber, Owner

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


@cache
def _extract(doc_id: str):
    # OCR is slow enough that re-running it per test (several tests share
    # the same fixture) would make the suite noticeably slower for no
    # benefit; `extract_scanned` is a pure function of its bytes.
    pdf_bytes = (FIXTURES / f"house_scanned_{doc_id}.pdf").read_bytes()
    return extract_scanned(pdf_bytes, bronze_key=f"bronze/house/year=2021/{doc_id}.pdf")


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------


def test_filing_row_carries_filing_metadata_and_provenance():
    result = _extract("8217884")

    filing = result.filing
    assert filing.doc_id == "8217884"
    assert filing.chamber is Chamber.HOUSE
    assert filing.filer_name == "Charles J. Fleischmann"
    assert filing.filing_date == date(2021, 3, 3)
    assert filing.year == 2021
    assert filing.confidence == FULL_CONFIDENCE
    assert filing.provenance.bronze_key == "bronze/house/year=2021/8217884.pdf"
    assert filing.provenance.extractor == EXTRACTOR_NAME


def test_doc_id_comes_from_the_bronze_key_not_ocr():
    # Scanned filings have no "Filing ID #" footer to read as text (unlike
    # the digital extractor); the doc id is the one thing that must come
    # from the caller-supplied bronze key instead of OCR.
    result = _extract("8217884")

    assert result.filing.doc_id == "8217884"


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def test_transaction_type_and_value_range_are_always_null_at_low_confidence():
    # Both are hand/typed checkbox grids on the paper form (ADR 0002 and its
    # #37 addendum); full-page OCR of a checkbox is noise, never a value.
    result = _extract("8217884")

    assert result.transactions
    for transaction in result.transactions:
        assert transaction.transaction_type is None
        assert transaction.transaction_type_raw == ""
        assert transaction.value_range is None
        assert transaction.field_confidence["transaction_type"] == 0.0
        assert transaction.field_confidence["value_range"] == 0.0


def test_asset_name_and_transaction_date_are_recovered_from_ocr():
    result = _extract("8217884")

    assert len(result.transactions) == 6
    first = result.transactions[0]
    assert "ISHARES IBONDS DEC" in first.asset_description
    assert first.transaction_date == date(2021, 1, 21)
    assert first.notification_date == date(2021, 2, 1)
    assert first.doc_id == "8217884"
    assert first.line_no == 1
    assert first.owner is Owner.SELF
    assert first.field_confidence["transaction_date"] == FULL_CONFIDENCE
    assert first.confidence == 0.0  # lowest field (transaction_type/value_range) wins


def test_a_row_ocr_could_not_date_is_dropped_not_guessed():
    # The last two rows only ever recover one of the two printed dates; the
    # missing one stays null and low-confidence rather than copied from a
    # neighbouring row.
    result = _extract("8217884")

    last_two = result.transactions[-2:]
    assert all(t.notification_date is None for t in last_two)
    assert all(t.field_confidence["notification_date"] == 0.0 for t in last_two)
    assert all(t.transaction_date is not None for t in last_two)


def test_asset_type_is_other_at_low_confidence_when_the_code_suffix_is_unreadable():
    # These rows' "[XX]" asset-type code sits past the asset-name crop's
    # boundary and is never recovered; OTHER at low confidence is honest,
    # not a guessed stock/ETF classification.
    result = _extract("8217884")

    assert all(t.asset_type is AssetType.OTHER for t in result.transactions)
    assert all(t.field_confidence["asset_type"] == 0.0 for t in result.transactions)
    assert all(t.ticker is None for t in result.transactions)


# ---------------------------------------------------------------------------
# Honest failure
# ---------------------------------------------------------------------------


def test_unreadable_filer_name_or_stamp_raises_rather_than_guessing():
    # This fixture's date-received stamp OCRs too noisily to parse; every
    # `Filing` field is required, so the honest outcome is a raised error,
    # not a Filing built from a guessed date.
    pdf_bytes = (FIXTURES / "house_scanned_8218417.pdf").read_bytes()

    with pytest.raises(ValueError, match="missing filer name or date-received stamp"):
        extract_scanned(pdf_bytes, bronze_key="bronze/house/year=2021/8218417.pdf")
