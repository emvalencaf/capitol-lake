"""Digital House PDF extractor, exercised against real sampled House PTRs.

Every fixture is an unmodified House digital PTR PDF (`ptr-pdfs/2025/<doc_id>.pdf`),
so these tests pin the field values the extractor resolves to, not the
pypdf text it resolves them from.
"""

import math
from datetime import date
from pathlib import Path

import pytest

from capitol_lake.schema import AssetType, Chamber, Owner, TransactionType, ValueRange
from capitol_lake.stages.digital_extract import (
    EXTRACTOR_NAME,
    LOW_CONFIDENCE,
    extract_digital,
    parse_value_range,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _extract(doc_id: str):
    pdf_bytes = (FIXTURES / f"house_digital_{doc_id}.pdf").read_bytes()
    return extract_digital(pdf_bytes, bronze_key=f"bronze/house/year=2025/{doc_id}.pdf")


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------


def test_filing_row_carries_filing_metadata_and_provenance():
    result = _extract("20030646")

    filing = result.filing
    assert filing.doc_id == "20030646"
    assert filing.chamber is Chamber.HOUSE
    assert filing.filer_name == "Hon. Cliff Bentz"
    assert filing.filing_date == date(2025, 7, 9)
    assert filing.year == 2025
    assert filing.confidence == 1.0
    assert filing.provenance.bronze_key == "bronze/house/year=2025/20030646.pdf"
    assert filing.provenance.extractor == EXTRACTOR_NAME


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def test_transaction_rows_match_the_filing_line_by_line():
    result = _extract("20030646")

    first, second = result.transactions
    assert first.doc_id == second.doc_id == "20030646"
    assert (first.line_no, second.line_no) == (1, 2)

    assert first.owner is Owner.SPOUSE
    assert first.owner_raw == "SP"
    assert first.asset_description == "Amgen Inc. - Common Stock (AMGN) [ST]"
    assert first.asset_type is AssetType.STOCK
    assert first.transaction_type is TransactionType.PURCHASE
    assert first.transaction_type_raw == "P"
    assert first.transaction_date == date(2025, 6, 6)
    assert first.notification_date == date(2025, 7, 1)
    assert first.value_range == ValueRange(1_001, 15_000)
    assert first.disclosure_lag == (date(2025, 7, 9) - date(2025, 6, 6)).days
    assert first.filing_status == "New"
    assert first.sub_owner == "Charles Schwab SEP-IRA"
    assert first.description is None
    assert first.confidence == 1.0
    assert first.provenance.bronze_key == "bronze/house/year=2025/20030646.pdf"
    assert first.provenance.extractor == EXTRACTOR_NAME

    assert second.asset_description == "Procter & Gamble Company (PG) [ST]"


def test_absent_sub_owner_line_nulls_the_field_instead_of_borrowing_a_neighbour():
    # The second transaction has no "Subholding Of" line: the next line is the
    # asset-type footnote. A positional walk would read that line as sub_owner.
    second = _extract("20030646").transactions[1]

    assert second.sub_owner is None
    assert second.field_confidence["sub_owner"] == LOW_CONFIDENCE
    assert second.filing_status == "New"
    assert second.field_confidence["filing_status"] == 1.0


def test_matched_labels_are_reported_at_full_field_confidence():
    first = _extract("20030646").transactions[0]

    assert first.field_confidence["sub_owner"] == 1.0
    assert first.field_confidence["filing_status"] == 1.0
    assert first.field_confidence["description"] == LOW_CONFIDENCE


def test_notification_date_before_transaction_date_is_surfaced_uncorrected():
    # Known source bug (#30): lines 3 and 4 of this filing print a 2024
    # notification date for a December 2024 transaction. The extractor keeps
    # both dates exactly as printed rather than guessing a correction.
    transactions = _extract("20026537").transactions

    buggy = transactions[2]
    assert buggy.transaction_date == date(2024, 12, 3)
    assert buggy.notification_date == date(2024, 1, 8)
    assert buggy.notification_date < buggy.transaction_date
    assert buggy.disclosure_lag == (date(2025, 1, 16) - date(2024, 12, 3)).days

    assert [t.notification_date < t.transaction_date for t in transactions] == [
        False,
        False,
        True,
        True,
    ]


def test_self_owned_line_without_owner_code_resolves_to_self():
    third = _extract("20026537").transactions[2]

    assert third.owner is Owner.SELF
    assert third.owner_raw == ""
    assert third.asset_description == "US TREASURY BILL DUE 03/20/25 (912797KJ5) [GS]"
    assert third.asset_type is AssetType.BOND
    assert third.sub_owner == "SCH1"


def test_value_range_split_across_two_lines_is_joined():
    first = _extract("20026537").transactions[0]

    assert first.value_range == ValueRange(15_001, 50_000)


def test_transaction_line_sharing_the_asset_line_and_description_label():
    transactions = _extract("20026517").transactions

    exchange, duke_street = transactions[0], transactions[1]
    assert exchange.transaction_type is TransactionType.EXCHANGE
    assert exchange.owner is Owner.JOINT
    assert exchange.description == "Called Security"

    assert duke_street.asset_description == "Duke Street LLC, 50% Interest [OI]"
    assert duke_street.asset_type is AssetType.OTHER
    assert duke_street.transaction_type is TransactionType.SALE_FULL
    assert duke_street.value_range == ValueRange(5_000_001, 25_000_000)
    assert duke_street.sub_owner == "Real estate investments"
    assert duke_street.description == "sale of 2712 Duke Street, Alexandria, Virginia"


def test_multi_page_filing_keeps_every_line_across_page_breaks():
    transactions = _extract("20026533").transactions

    assert len(transactions) == 55
    assert [t.line_no for t in transactions] == list(range(1, 56))
    # Every line in this filing has a "Subholding Of" line, some of them
    # pushed onto the next page past the repeated column header.
    assert all(t.sub_owner is not None for t in transactions)
    assert all(t.filing_status == "New" for t in transactions)


def test_multi_page_filing_resolves_partial_sales_and_options():
    transactions = _extract("20026533").transactions

    alibaba = transactions[0]
    assert alibaba.asset_description == (
        "Alibaba Group Holding Limited American Depositary Shares each "
        "representing eight Ordinary share (BABA) [ST]"
    )
    assert alibaba.transaction_type is TransactionType.SALE_FULL

    ambev = transactions[1]
    assert ambev.transaction_type is TransactionType.SALE_PARTIAL
    assert ambev.transaction_type_raw == "S (partial)"

    options = [t for t in transactions if t.asset_type is AssetType.OPTION]
    assert options
    assert all(t.description and t.description.startswith("Call options") for t in options)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,001 - $15,000", ValueRange(1_001, 15_000)),
        ("Over $50,000,000", ValueRange(50_000_001, math.inf)),
        ("Spouse/DC Over $1,000,000", ValueRange(1_000_001, math.inf)),
    ],
)
def test_parse_value_range(raw, expected):
    assert parse_value_range(raw) == expected
