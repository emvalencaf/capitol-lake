"""Senate HTML extractor, exercised against a real sampled Senate `/ptr/` page
plus small synthetic pages for edge cases the sample doesn't cover.

`senate_ptr_sample.html` is an unmodified Senate eFD print view (`filedReport`
header, 4-row transactions table covering a Purchase-with-option, a
Sale (Full), and an Exchange, all Owner=Joint), so the tests against it pin
field values the extractor resolves from real markup. The synthetic pages
below exercise paths the sample has no row for: Sale (Partial), a non-Joint
owner, an unrecognized Owner/Type string, a filer with no honorific, a filing
with zero transactions, and a page missing the expected table.
"""

from datetime import date
from pathlib import Path

import pytest

from extract_data.senate_extract import (
    EXTRACTOR_NAME,
    FULL_CONFIDENCE,
    SenateFilingFormatError,
    UnknownSenateOwnerError,
    UnknownSenateTransactionTypeError,
    extract_senate_html,
)
from shared.schema import AssetType, Chamber, Owner, TransactionType

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

BRONZE_KEY = "bronze/senate/year=2026/11111111-1111-1111-1111-111111111111.html"
DOC_ID = "11111111-1111-1111-1111-111111111111"


def _extract_sample():
    html_bytes = (FIXTURES / "senate_ptr_sample.html").read_bytes()
    return extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)


def _page(
    *,
    header: str = "Mr. Alan Armstrong (Armstrong, Alan)",
    filed: str = "Filed  09/17/2026 @ 8:55 AM",
    rows: str = "",
    with_table: bool = True,
) -> bytes:
    table = (
        f"""
        <table class="table table-striped">
            <thead>
                <tr class="header">
                    <th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th>
                    <th>Asset Name</th><th>Asset Type</th><th>Type</th><th>Amount</th>
                    <th>Comment</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        """
        if with_table
        else ""
    )
    return f"""
    <html><body>
        <h2 class="filedReport">{header}</h2>
        <p class="muted">{filed}</p>
        {table}
    </body></html>
    """.encode()


def _row(
    *,
    line_no: int = 1,
    txn_date: str = "08/19/2026",
    owner: str = "Joint",
    ticker: str = "WMB",
    asset: str = "Williams Companies, Inc. (The) Common Stock",
    asset_type: str = "Stock",
    txn_type: str = "Purchase",
    amount: str = "$1,001 - $15,000",
    comment: str = "--",
) -> str:
    return f"""
    <tr>
        <td>{line_no}</td>
        <td>{txn_date}</td>
        <td>{owner}</td>
        <td><a href="https://finance.yahoo.com/quote/{ticker}">{ticker}</a></td>
        <td>{asset}</td>
        <td>{asset_type}</td>
        <td>{txn_type}</td>
        <td>{amount}</td>
        <td>{comment}</td>
    </tr>
    """


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------


def test_filing_row_carries_filing_metadata_and_provenance():
    result = _extract_sample()

    filing = result.filing
    assert filing.doc_id == DOC_ID
    assert filing.chamber is Chamber.SENATE
    assert filing.filer_name == "Alan Armstrong"
    assert filing.filing_date == date(2026, 9, 17)
    assert filing.year == 2026
    assert filing.confidence == FULL_CONFIDENCE
    assert filing.provenance.bronze_key == BRONZE_KEY
    assert filing.provenance.extractor == EXTRACTOR_NAME


def test_filer_name_strips_honorific_and_last_first_parenthetical():
    html_bytes = _page(header="Dr. Jane Q. Smith (Smith, Jane Q.)")

    result = extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)

    assert result.filing.filer_name == "Jane Q. Smith"


def test_filer_name_survives_no_honorific_at_all():
    html_bytes = _page(header="John Smith (Smith, John)")

    result = extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)

    assert result.filing.filer_name == "John Smith"


def test_filing_with_no_transaction_rows_is_valid_not_an_error():
    html_bytes = _page(rows="")

    result = extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)

    assert result.transactions == []


def test_missing_transactions_table_raises_format_error():
    html_bytes = _page(with_table=False)

    with pytest.raises(SenateFilingFormatError):
        extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)


def test_missing_filed_line_raises_format_error():
    html_bytes = _page(filed="")

    with pytest.raises(SenateFilingFormatError):
        extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)


# ---------------------------------------------------------------------------
# Transactions: real sample
# ---------------------------------------------------------------------------


def test_transaction_line_numbers_are_the_source_hash_column_verbatim():
    # The sample's rows print "#" in descending order (4, 3, 2, 1); line_no
    # must match the printed value, not the table's reading-order position.
    result = _extract_sample()

    assert [t.line_no for t in result.transactions] == [4, 3, 2, 1]


def test_option_row_ticker_and_option_details_land_in_description():
    result = _extract_sample()
    option_row = next(t for t in result.transactions if t.line_no == 4)

    assert option_row.ticker == "WMB"
    assert option_row.asset_type is AssetType.OPTION
    assert option_row.asset_description == "Williams Companies, Inc. (The) Common Stock"
    assert option_row.description == "Option Type: Call Strike price: $75.00 Expires: 2026-08-21"
    assert option_row.transaction_type is TransactionType.PURCHASE
    assert option_row.owner is Owner.JOINT


def test_plain_stock_row_has_no_ticker_and_no_description():
    result = _extract_sample()
    sale_row = next(t for t in result.transactions if t.line_no == 3)

    assert sale_row.ticker is None
    assert sale_row.asset_type is AssetType.STOCK
    assert sale_row.asset_description == "Electronic Arts Inc. (EA)"
    assert sale_row.description is None
    assert sale_row.transaction_type is TransactionType.SALE_FULL


def test_exchange_row_splits_given_up_and_received_legs():
    result = _extract_sample()
    exchange_row = next(t for t in result.transactions if t.line_no == 2)

    assert exchange_row.transaction_type is TransactionType.EXCHANGE
    assert exchange_row.asset_description == (
        "AvalonBay Communities, Inc. Common Stock (AVB) (Exchanged)"
    )
    assert exchange_row.description == (
        "VMRK - Vivmark Residential Common Shares of Beneficial Interest (Received)"
    )
    assert exchange_row.ticker is None


def test_comment_column_text_is_never_persisted():
    result = _extract_sample()
    row_with_comment = next(t for t in result.transactions if t.line_no == 1)

    # The sample's row 1 has "All transactions notified to Filer on
    # September 1, 2026" in its Comment column; per ADR 0013 this is dropped
    # entirely, not stored anywhere and not parsed into notification_date.
    # (Its `description` still holds that row's Option details, unrelated to
    # the Comment column.)
    assert row_with_comment.notification_date is None
    assert row_with_comment.filing_status is None
    assert row_with_comment.sub_owner is None


def test_every_row_is_full_confidence_with_no_field_confidence_entries():
    result = _extract_sample()

    for transaction in result.transactions:
        assert transaction.confidence == FULL_CONFIDENCE
        assert transaction.field_confidence == {}


# ---------------------------------------------------------------------------
# Transactions: synthetic edge cases
# ---------------------------------------------------------------------------


def test_sale_partial_transaction_type_is_recognized():
    html_bytes = _page(rows=_row(txn_type="Sale (Partial)"))

    result = extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)

    assert result.transactions[0].transaction_type is TransactionType.SALE_PARTIAL
    assert result.transactions[0].transaction_type_raw == "Sale (Partial)"


def test_non_joint_owner_is_recognized():
    html_bytes = _page(rows=_row(owner="Dependent Child"))

    result = extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)

    assert result.transactions[0].owner is Owner.DEPENDENT_CHILD
    assert result.transactions[0].owner_raw == "Dependent Child"


def test_unrecognized_owner_raises_rather_than_miscategorizing():
    html_bytes = _page(rows=_row(owner="Trustee"))

    with pytest.raises(UnknownSenateOwnerError):
        extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)


def test_unrecognized_transaction_type_raises_rather_than_miscategorizing():
    html_bytes = _page(rows=_row(txn_type="Gift"))

    with pytest.raises(UnknownSenateTransactionTypeError):
        extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)


def test_unrecognized_asset_type_falls_back_to_other():
    html_bytes = _page(rows=_row(asset_type="Cryptocurrency ETF"))

    result = extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)

    assert result.transactions[0].asset_type is AssetType.OTHER


def test_two_text_muted_divs_are_both_kept_not_just_the_first():
    # A private-stock ("Other" asset type) row confirmed against a real
    # sampled filing (eval#40-senate): the asset cell carries both a
    # `Company:` and a `Description:` text-muted div. Both must survive.
    asset_cell = """
    <td>
        More
        <div class="text-muted"><em>Company:</em> More&nbsp;(Ebene, Mauritius)</div>
        <div class="text-muted"><em>Description:</em>&nbsp;Grocery Chain</div>
    </td>
    """
    row = f"""
    <tr>
        <td>1</td>
        <td>10/04/2022</td>
        <td>Self</td>
        <td>--</td>
        {asset_cell}
        <td>Other</td>
        <td>Purchase</td>
        <td>$1,001 - $15,000</td>
        <td>--</td>
    </tr>
    """
    html_bytes = _page(rows=row)

    result = extract_senate_html(html_bytes, bronze_key=BRONZE_KEY, doc_id=DOC_ID)

    transaction = result.transactions[0]
    assert transaction.asset_description == "More"
    assert transaction.asset_type is AssetType.OTHER
    assert "Company:" in transaction.description
    assert "Description:" in transaction.description
