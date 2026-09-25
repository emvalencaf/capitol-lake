"""Digital House PDF extractor, exercised against real sampled House PTRs.

Every fixture is an unmodified House digital PTR PDF (`ptr-pdfs/2025/<doc_id>.pdf`),
so these tests pin the field values the extractor resolves to, not the
pypdf text it resolves them from.
"""

from datetime import date
from pathlib import Path

import pytest

from capitol_lake.schema import AssetType, Chamber, Owner, TransactionType, ValueRange
from capitol_lake.stages.digital_extract import (
    EXTRACTOR_NAME,
    FULL_CONFIDENCE,
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
    assert second.filing_status == "New"


def test_a_label_absent_from_its_row_is_a_confident_null_not_a_low_confidence_one():
    # A row's lines are all accounted for, so a missing optional label means
    # the form has no such line, not that it couldn't be read: nothing for a
    # fallback stage to recover.
    first, second = _extract("20030646").transactions

    assert first.description is None
    assert second.sub_owner is None
    assert first.field_confidence == {
        "filing_status": FULL_CONFIDENCE,
        "sub_owner": FULL_CONFIDENCE,
        "description": FULL_CONFIDENCE,
        "asset_type": FULL_CONFIDENCE,
    }
    assert second.field_confidence["sub_owner"] == FULL_CONFIDENCE
    assert first.confidence == second.confidence == FULL_CONFIDENCE


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
        ("Over $50,000,000", ValueRange(50_000_001, None)),
        ("Spouse/DC Over $1,000,000", ValueRange(1_000_001, None)),
        ("$9.00", ValueRange(9, 9)),
        ("$569.25", ValueRange(569.25, 569.25)),
    ],
)
def test_parse_value_range(raw, expected):
    assert parse_value_range(raw) == expected


def test_literal_dollar_amount_under_the_bracket_threshold():
    # 20022260 (Pelosi, 2023): a dividend-reinvestment line prints a bare
    # "$9.00" instead of a bracket. Regression test for #57.
    transactions = _extract("20022260").transactions

    literal = next(t for t in transactions if t.value_range == ValueRange(9, 9))
    assert literal.value_range.min == literal.value_range.max == 9


def test_multiple_literal_dollar_amounts_in_one_filing():
    # 20023819 (Sessions, 2023): two lines each print a bare literal amount.
    # Regression test for #57.
    transactions = _extract("20023819").transactions

    value_ranges = {t.value_range for t in transactions}
    assert ValueRange(569.25, 569.25) in value_ranges
    assert ValueRange(493.91, 493.91) in value_ranges


def test_absent_sub_owner_mid_table_nulls_the_field_instead_of_borrowing_the_next_asset():
    # Lines 1 and 2 of this filing have no "Subholding Of" line: each is
    # followed directly by the next transaction's asset line, which a
    # positional walk would read as sub_owner.
    transactions = _extract("20026696").transactions

    assert [t.asset_description for t in transactions] == [
        "Ethereum Crypto currency [CT]",
        "Virtuals Protocol [CT]",
        "Virtuals Protocol [CT]",
    ]
    assert all(t.sub_owner is None for t in transactions)
    assert all(t.field_confidence["sub_owner"] == FULL_CONFIDENCE for t in transactions)
    assert all(t.filing_status == "New" for t in transactions)
    assert transactions[0].asset_type is AssetType.CRYPTOCURRENCY


def test_asset_text_wrapped_past_a_page_break_stays_on_its_own_line():
    # Line 16's transaction line ends page 2; its "(EOG) [ST]" asset tail and
    # its labelled lines continue under page 3's repeated column header.
    transactions = _extract("20030482").transactions

    assert len(transactions) == 54
    eog, ge = transactions[15], transactions[16]
    assert eog.asset_description == "EOG Resources, Inc. Common Stock (EOG) [ST]"
    assert eog.asset_type is AssetType.STOCK
    assert eog.filing_status == "New"
    assert eog.sub_owner == "JP Morgan Brokerage Account"
    assert ge.asset_description == "GE Aerospace Common Stock (GE) [ST]"
    assert all(t.sub_owner is not None for t in transactions)
    assert all(t.asset_description.endswith("[ST]") for t in transactions)


def test_amount_upper_bound_sharing_a_line_with_wrapped_asset_text_past_a_page_break():
    # A transaction line ending page 2 with "$15,001 -" continues on page 3
    # as "Common Stock (BRK.B) [ST] $50,000": asset tail and amount max share
    # one line.
    transactions = _extract("20024346").transactions

    assert len(transactions) == 130
    split = transactions[22]
    assert split.owner is Owner.JOINT
    assert split.transaction_type is TransactionType.PURCHASE
    assert split.notification_date == date(2025, 1, 13)
    assert split.asset_description == "Berkshire Hathaway Inc. New Common Stock (BRK.B) [ST]"
    assert split.value_range == ValueRange(15_001, 50_000)
    assert split.sub_owner == "Joint Ownership LPL Account"
    assert all("\x00" not in t.asset_description for t in transactions)


def test_wrapped_label_value_stays_with_its_own_line_not_the_next_asset():
    # Each "Comments:" value in this filing wraps over three lines, directly
    # above the next transaction's asset line.
    transactions = _extract("20033574").transactions

    assert len(transactions) == 12
    first, second = transactions[0], transactions[1]
    assert first.asset_description == "Berkshire Hathaway Inc. New Common Stock (BRK.B) [ST]"
    assert first.description == "Buy to Close Covered Call Contract"
    assert second.asset_description == "BRKB Option [OT]"
    assert second.value_range == ValueRange(15_001, 50_000)
    assert second.sub_owner == "LPL Account I"
    assert second.description == "CALL BERKSHIRE CL B NEW $380 EXP 01/16/26"
    assert all(t.filing_status == "New" for t in transactions)
    assert all(t.asset_description.endswith(("[ST]", "[OT]", "[GS]")) for t in transactions)
    assert not any("advisor" in t.asset_description for t in transactions)


def test_2021_form_template_with_scrambled_label_case_and_checkbox_glyphs():
    # The 2021 form renders labels in small caps ("F IlINg S TATuS :"), maps
    # some capitals to lowercase, and draws the cap-gains checkboxes as glyph
    # text between the asset lines.
    result = _extract("20019582")

    assert result.filing.filer_name == "Hon. Patrick Fallon"
    assert result.filing.filing_date == date(2021, 10, 5)
    transactions = result.transactions
    assert len(transactions) == 18
    assert all(t.filing_status == "New" for t in transactions)
    assert transactions[0].asset_description == "Amazon.com, Inc. (AMZN) [ST]"
    assert transactions[1].asset_description == "American Airlines group, Inc. (AAl) [ST]"
    assert transactions[3].asset_description == "CrowdStrike Holdings, I nc. - Class A (CRWD) [ST]"
    assert transactions[4].value_range == ValueRange(100_001, 250_000)
    verizon = next(t for t in transactions if "Verizon" in t.asset_description)
    assert verizon.asset_description == "Verizon Communications Inc. (VZ) [ST]"


def test_printed_symbol_fills_ticker_for_stock_and_etf_lines_only():
    transactions = _extract("20026537").transactions + _extract("20030646").transactions

    tickers = {t.asset_description: t.ticker for t in transactions}
    assert tickers["Amgen Inc. - Common Stock (AMGN) [ST]"] == "AMGN"
    assert tickers["Procter & Gamble Company (PG) [ST]"] == "PG"
    assert tickers["Rollins, Inc. Common Stock (ROL) [ST]"] == "ROL"
    # A bond's parenthesized CUSIP is not a ticker.
    assert tickers["US TREASURY BILL DUE 03/20/25 (912797KJ5) [GS]"] is None


def test_printed_symbol_keeps_share_class_punctuation():
    transactions = _extract("20024346").transactions

    assert {t.ticker for t in transactions if "Berkshire" in t.asset_description} >= {"BRK.B"}
    assert all(t.ticker is None for t in transactions if t.asset_type is AssetType.OPTION)


def test_printed_symbol_is_uppercased_where_the_2021_font_lowercased_it():
    transactions = _extract("20019582").transactions

    assert transactions[1].asset_description == "American Airlines group, Inc. (AAl) [ST]"
    assert transactions[1].ticker == "AAL"
    assert transactions[0].ticker == "AMZN"
