"""Extract stage: doc-id routing plus Hive-partitioned silver Parquet.

Reuses the same real House PTR fixtures as `test_digital_extract.py` and
`test_scanned_extract.py` so routing is exercised end-to-end against real
bytes, not synthetic ones, then verifies the returned Parquet bytes are
actually queryable (round-tripped with pyarrow) rather than just checking
they're non-empty.
"""

import dataclasses
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from capitol_lake.schema import AssetType
from capitol_lake.stages import extract as extract_module
from capitol_lake.stages.extract import (
    DocIdMismatchError,
    UnrecognizedBronzeKeyError,
    extract_house_filing,
)
from capitol_lake.stages.house_collect import UnknownDocIdPrefixError

FIXTURES = Path(__file__).parent / "fixtures"


def _read_parquet(data: bytes):
    import io

    return pq.read_table(io.BytesIO(data))


def test_digital_doc_id_routes_to_digital_extractor_and_writes_silver_keys():
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()

    result = extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2025/20030646.pdf")

    assert result["kind"] == "digital"
    assert (
        result["filings"]["key"] == "silver/filings/chamber=house/year=2025/part-20030646.parquet"
    )
    assert (
        result["transactions"]["key"]
        == "silver/transactions/chamber=house/year=2025/part-20030646.parquet"
    )


def test_scanned_doc_id_routes_to_scanned_extractor_and_writes_silver_keys():
    pdf_bytes = (FIXTURES / "house_scanned_8217884.pdf").read_bytes()

    result = extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2021/8217884.pdf")

    assert result["kind"] == "scanned"
    assert result["filings"]["key"] == "silver/filings/chamber=house/year=2021/part-8217884.parquet"
    assert (
        result["transactions"]["key"]
        == "silver/transactions/chamber=house/year=2021/part-8217884.parquet"
    )


def test_unknown_doc_id_prefix_is_never_silently_routed():
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()

    with pytest.raises(UnknownDocIdPrefixError):
        extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2025/99999999.pdf")


def test_malformed_bronze_key_is_rejected():
    with pytest.raises(UnrecognizedBronzeKeyError):
        extract_house_filing(b"", bronze_key="not-a-bronze-key")


def test_filings_parquet_is_queryable_with_the_filing_metadata():
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()

    result = extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2025/20030646.pdf")

    table = _read_parquet(result["filings"]["bytes"])
    assert table.num_rows == 1
    row = table.to_pylist()[0]
    assert row["doc_id"] == "20030646"
    assert row["chamber"] == "house"
    assert row["filer_name"] == "Hon. Cliff Bentz"
    assert row["bronze_key"] == "bronze/house/year=2025/20030646.pdf"


def test_transactions_parquet_always_carries_asset_type_and_description():
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()

    result = extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2025/20030646.pdf")

    table = _read_parquet(result["transactions"]["bytes"])
    assert table.num_rows == 2
    for row in table.to_pylist():
        assert row["asset_type"]
        assert row["asset_description"]
        assert row["doc_id"] == "20030646"


def test_unreadable_scanned_filing_raises_before_writing():
    # 8218417 is real scan noise the extractor can't read a filer name or
    # filing date from at all (ADR 0002); extraction raises before this
    # stage ever gets to serialize a row.
    pdf_bytes = (FIXTURES / "house_scanned_8218417.pdf").read_bytes()

    with pytest.raises(ValueError):
        extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2021/8218417.pdf")


def test_doc_id_disagreeing_with_the_bronze_key_is_never_silently_written():
    # The PDF's own "Filing ID #" footer says 20030646; giving it a bronze
    # key under a different doc id must raise rather than write the row
    # under a partition path that disagrees with its own doc_id field.
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()

    with pytest.raises(DocIdMismatchError):
        extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2025/20099999.pdf")


def test_resolve_ticker_fills_only_still_null_stock_and_etf_rows():
    # 20030646 has both a bond (CUSIP, never a ticker candidate) and stock
    # rows whose printed symbol already fills `ticker` (see
    # test_digital_extract.py's printed-symbol tests) - resolve_ticker must
    # never be asked about either of those, only a still-null stock/ETF row.
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()
    calls: list[tuple[str, AssetType]] = []

    def _resolve_ticker(asset_description: str, asset_type: AssetType) -> str | None:
        calls.append((asset_description, asset_type))
        return None

    extract_house_filing(
        pdf_bytes,
        bronze_key="bronze/house/year=2025/20030646.pdf",
        resolve_ticker=_resolve_ticker,
    )

    assert calls == []


def test_resolve_ticker_result_lands_on_a_still_null_stock_row(monkeypatch):
    # No sampled fixture has a stock/ETF line with no printed symbol, so the
    # digital extractor's own output is faked here to exercise the one case
    # resolve_ticker exists for: a still-null stock/ETF ticker.
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()
    extraction = extract_module.extract_digital(
        pdf_bytes, bronze_key="bronze/house/year=2025/20030646.pdf"
    )
    unresolved = dataclasses.replace(
        extraction.transactions[0],
        ticker=None,
        asset_type=AssetType.STOCK,
        filing_date=extraction.filing.filing_date,
    )
    faked = dataclasses.replace(extraction, transactions=[unresolved])
    monkeypatch.setitem(extract_module._EXTRACTORS, "digital", lambda *a, **k: faked)

    def _resolve_ticker(asset_description: str, asset_type: AssetType) -> str | None:
        assert asset_type is AssetType.STOCK
        return "RESOLVED"

    result = extract_house_filing(
        pdf_bytes,
        bronze_key="bronze/house/year=2025/20030646.pdf",
        resolve_ticker=_resolve_ticker,
    )

    table = _read_parquet(result["transactions"]["bytes"])
    assert table.to_pylist()[0]["ticker"] == "RESOLVED"


def test_llm_fallback_is_applied_before_ticker_resolution():
    # llm_fallback is called for every row, and its output feeds
    # resolve_ticker (still-null ticker, stock/ETF asset_type) - here it
    # rewrites asset_type to STOCK so resolve_ticker gets called at all.
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()
    fallback_calls: list[str] = []
    resolve_calls: list[AssetType] = []

    def _llm_fallback(transaction):
        fallback_calls.append(transaction.doc_id)
        return dataclasses.replace(
            transaction,
            asset_type=AssetType.STOCK,
            ticker=None,
            filing_date=date(2025, 6, 2),
        )

    def _resolve_ticker(asset_description: str, asset_type: AssetType) -> str | None:
        resolve_calls.append(asset_type)
        return "RESOLVED"

    result = extract_house_filing(
        pdf_bytes,
        bronze_key="bronze/house/year=2025/20030646.pdf",
        llm_fallback=_llm_fallback,
        resolve_ticker=_resolve_ticker,
    )

    assert len(fallback_calls) == 2
    assert resolve_calls == [AssetType.STOCK, AssetType.STOCK]
    table = _read_parquet(result["transactions"]["bytes"])
    assert all(row["ticker"] == "RESOLVED" for row in table.to_pylist())


def test_no_llm_fallback_argument_performs_no_fallback():
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()

    result = extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2025/20030646.pdf")

    table = _read_parquet(result["transactions"]["bytes"])
    assert table.num_rows == 2


def test_no_resolve_ticker_argument_performs_no_resolution():
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()

    result = extract_house_filing(pdf_bytes, bronze_key="bronze/house/year=2025/20030646.pdf")

    table = _read_parquet(result["transactions"]["bytes"])
    # Same rows as every other test above that omits resolve_ticker: nothing
    # about the fixture's own tickers changes when no cascade is wired in.
    assert table.num_rows == 2
