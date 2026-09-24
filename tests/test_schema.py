from datetime import date

import pytest

from capitol_lake.schema import (
    AssetType,
    Chamber,
    Filing,
    Owner,
    Provenance,
    Transaction,
    TransactionType,
    ValueRange,
)


def _provenance(**overrides) -> Provenance:
    fields = {
        "bronze_key": "bronze/house/year=2024/20012345.pdf",
        "extractor": "house-digital-pdf",
    }
    fields.update(overrides)
    return Provenance(**fields)


def test_filing_example_row_validates():
    filing = Filing(
        doc_id="20012345",
        chamber=Chamber.HOUSE,
        filer_name="Jane Doe",
        filing_date=date(2024, 2, 1),
        year=2024,
        confidence=0.95,
        provenance=_provenance(),
    )

    assert filing.doc_id == "20012345"
    assert filing.chamber is Chamber.HOUSE


def test_transaction_example_row_validates():
    transaction = Transaction(
        doc_id="20012345",
        line_no=1,
        owner=Owner.SPOUSE,
        owner_raw="SP",
        transaction_type=TransactionType.PURCHASE,
        transaction_type_raw="P",
        asset_type=AssetType.STOCK,
        asset_description="Apple Inc. Common Stock",
        transaction_date=date(2024, 1, 10),
        filing_date=date(2024, 2, 1),
        value_range=ValueRange(min=1001, max=15000),
        confidence=0.8,
        provenance=_provenance(),
    )

    assert transaction.disclosure_lag == 22
    assert transaction.value_range == ValueRange(min=1001, max=15000)
    assert transaction.ticker is None
    assert not hasattr(transaction, "member_id")


def test_transaction_disclosure_lag_cannot_be_set_directly():
    with pytest.raises(TypeError):
        Transaction(
            doc_id="20012345",
            line_no=1,
            owner=Owner.SPOUSE,
            owner_raw="SP",
            transaction_type=TransactionType.PURCHASE,
            transaction_type_raw="P",
            asset_type=AssetType.STOCK,
            asset_description="Apple Inc. Common Stock",
            transaction_date=date(2024, 1, 10),
            filing_date=date(2024, 2, 1),
            value_range=ValueRange(min=1001, max=15000),
            confidence=0.8,
            provenance=_provenance(),
            disclosure_lag=999,
        )


def test_value_range_rejects_max_below_min():
    with pytest.raises(ValueError):
        ValueRange(min=1000, max=500)


def test_value_range_rejects_negative_min():
    with pytest.raises(ValueError):
        ValueRange(min=-1, max=500)


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValueError):
        Filing(
            doc_id="20012345",
            chamber=Chamber.HOUSE,
            filer_name="Jane Doe",
            filing_date=date(2024, 2, 1),
            year=2024,
            confidence=1.5,
            provenance=_provenance(),
        )


def test_transaction_type_enum_includes_senate_exchange():
    assert TransactionType.EXCHANGE.value == "exchange"


def test_disclosure_lag_can_be_negative_without_raising():
    # Honest data: a filing can be dated before its own transaction date
    # (known extractor edge case); disclosure_lag must not hide that.
    transaction = Transaction(
        doc_id="20099999",
        line_no=1,
        owner=Owner.SELF,
        owner_raw="",
        transaction_type=TransactionType.SALE_FULL,
        transaction_type_raw="S (full)",
        asset_type=AssetType.STOCK,
        asset_description="Example Corp Common Stock",
        transaction_date=date(2024, 2, 10),
        filing_date=date(2024, 2, 1),
        value_range=ValueRange(min=1001, max=15000),
        confidence=0.3,
        provenance=_provenance(),
    )

    assert transaction.disclosure_lag == -9


def _transaction(**overrides) -> Transaction:
    fields = {
        "doc_id": "20012345",
        "line_no": 1,
        "owner": Owner.SELF,
        "owner_raw": "",
        "transaction_type": TransactionType.PURCHASE,
        "transaction_type_raw": "P",
        "asset_type": AssetType.STOCK,
        "asset_description": "Apple Inc. Common Stock",
        "transaction_date": date(2024, 1, 10),
        "filing_date": date(2024, 2, 1),
        "value_range": ValueRange(min=1001, max=15000),
        "confidence": 1.0,
        "provenance": _provenance(),
    }
    fields.update(overrides)
    return Transaction(**fields)


def test_optional_line_fields_default_to_null():
    transaction = _transaction()

    assert transaction.notification_date is None
    assert transaction.filing_status is None
    assert transaction.sub_owner is None
    assert transaction.description is None
    assert transaction.field_confidence == {}


def test_field_confidence_out_of_range_rejected():
    with pytest.raises(ValueError, match="confidence"):
        _transaction(field_confidence={"sub_owner": 1.5})


def test_value_range_max_is_null_for_an_open_ended_bracket():
    open_ended = ValueRange(min=50_000_001, max=None)

    assert open_ended.max is None


def test_transaction_with_field_confidence_is_hashable():
    transaction = _transaction(field_confidence={"sub_owner": 1.0})

    assert hash(transaction) == hash(_transaction(field_confidence={"sub_owner": 0.0}))
