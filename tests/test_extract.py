"""Extract stage: doc-id routing plus Hive-partitioned silver Parquet.

Reuses the same real House PTR fixtures as `test_digital_extract.py` and
`test_scanned_extract.py` so routing is exercised end-to-end against real
bytes, not synthetic ones, then verifies the returned Parquet bytes are
actually queryable (round-tripped with pyarrow) rather than just checking
they're non-empty.
"""

from pathlib import Path

import pyarrow.parquet as pq
import pytest

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
