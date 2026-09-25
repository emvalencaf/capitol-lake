"""Extract stage: House doc-id routing plus Hive-partitioned silver Parquet.

Given the bronze key of a House PTR, routes to the digital or scanned
extractor by the doc id's prefix (`route_doc_id`, from `house_collect`), then
serializes the resulting `Filing` and `Transaction` rows into two
Hive-partitioned Parquet part files, one per silver table (`filings`,
`transactions`), per ADR 0008. Every transaction row extracted is kept
regardless of `asset_type` — this stage only routes and serializes, it never
filters a row out. Like every other stage's pure function, this never
touches S3: it returns each part file's key and bytes, and the caller (a
handler) performs the actual write.

`resolve_ticker` (optional, injected like every other network dependency in
this codebase) fills a still-null `ticker` on stock/ETF rows via the
OpenFIGI + EDGAR cascade (`ticker_resolve.resolve_ticker`, #39), after the
extractor's own printed-symbol ticker; it is never called for a row that
already has a ticker or isn't stock/ETF, and its absence (the default)
leaves every row's ticker exactly as the extractor produced it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from capitol_lake.keys import silver_key
from capitol_lake.schema import AssetType, Filing, Transaction
from capitol_lake.stages.digital_extract import extract_digital
from capitol_lake.stages.house_collect import route_doc_id
from capitol_lake.stages.scanned_extract import extract_scanned
from capitol_lake.stages.ticker_resolve import TICKER_ASSET_TYPES

FILINGS_TABLE = "filings"
TRANSACTIONS_TABLE = "transactions"

_EXTRACTORS = {"digital": extract_digital, "scanned": extract_scanned}

# Reverses bronze_key()'s `bronze/<chamber>/year=<year>/<doc_id>.<ext>` layout.
_BRONZE_KEY_RE = re.compile(r"^bronze/(?P<chamber>[^/]+)/year=(?P<year>\d+)/(?P<doc_id>[^./]+)\.")

_FILING_SCHEMA = pa.schema(
    [
        ("doc_id", pa.string()),
        ("chamber", pa.string()),
        ("filer_name", pa.string()),
        ("filing_date", pa.date32()),
        ("year", pa.int32()),
        ("confidence", pa.float64()),
        ("bronze_key", pa.string()),
        ("extractor", pa.string()),
    ]
)

_TRANSACTION_SCHEMA = pa.schema(
    [
        ("doc_id", pa.string()),
        ("line_no", pa.int32()),
        ("owner", pa.string()),
        ("owner_raw", pa.string()),
        ("transaction_type", pa.string()),
        ("transaction_type_raw", pa.string()),
        ("asset_type", pa.string()),
        ("asset_description", pa.string()),
        ("transaction_date", pa.date32()),
        ("value_min", pa.float64()),
        ("value_max", pa.float64()),
        ("confidence", pa.float64()),
        ("bronze_key", pa.string()),
        ("extractor", pa.string()),
        ("ticker", pa.string()),
        ("notification_date", pa.date32()),
        ("filing_status", pa.string()),
        ("sub_owner", pa.string()),
        ("description", pa.string()),
        ("disclosure_lag", pa.int32()),
    ]
)


class UnrecognizedBronzeKeyError(ValueError):
    """A bronze key doesn't match the `bronze/<chamber>/year=<year>/<doc_id>.<ext>` layout."""


class DocIdMismatchError(ValueError):
    """The extracted `Filing.doc_id` disagrees with the bronze key's own doc id.

    The digital extractor reads `doc_id` from the PDF's own "Filing ID #"
    footer, independently of the bronze key it was fetched/stored under
    (unlike the scanned extractor, which has no such footer to read and
    always derives it from the bronze key). A silver row is partitioned by
    the bronze key's doc id (`silver_key`); writing it under a path that
    disagrees with the doc id inside the row itself would be a silent,
    undetectable data-integrity bug, so this is raised instead.
    """


def _parse_bronze_key(bronze_key: str) -> tuple[str, int, str]:
    match = _BRONZE_KEY_RE.match(bronze_key)
    if match is None:
        raise UnrecognizedBronzeKeyError(f"not a bronze key: {bronze_key!r}")
    return match.group("chamber"), int(match.group("year")), match.group("doc_id")


def _filing_row(filing: Filing) -> dict[str, Any]:
    return {
        "doc_id": filing.doc_id,
        "chamber": filing.chamber.value,
        "filer_name": filing.filer_name,
        "filing_date": filing.filing_date,
        "year": filing.year,
        "confidence": filing.confidence,
        "bronze_key": filing.provenance.bronze_key,
        "extractor": filing.provenance.extractor,
    }


def transaction_row(transaction: Transaction) -> dict[str, Any]:
    value_range = transaction.value_range
    return {
        "doc_id": transaction.doc_id,
        "line_no": transaction.line_no,
        "owner": transaction.owner.value,
        "owner_raw": transaction.owner_raw,
        "transaction_type": (
            transaction.transaction_type.value if transaction.transaction_type else None
        ),
        "transaction_type_raw": transaction.transaction_type_raw,
        "asset_type": transaction.asset_type.value,
        "asset_description": transaction.asset_description,
        "transaction_date": transaction.transaction_date,
        "value_min": value_range.min if value_range else None,
        "value_max": value_range.max if value_range else None,
        "confidence": transaction.confidence,
        "bronze_key": transaction.provenance.bronze_key,
        "extractor": transaction.provenance.extractor,
        "ticker": transaction.ticker,
        "notification_date": transaction.notification_date,
        "filing_status": transaction.filing_status,
        "sub_owner": transaction.sub_owner,
        "description": transaction.description,
        "disclosure_lag": transaction.disclosure_lag,
    }


def _parquet_bytes(rows: list[dict[str, Any]], schema: pa.Schema) -> bytes:
    table = pa.Table.from_pylist(rows, schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes()


def extract_house_filing(
    pdf_bytes: bytes,
    *,
    bronze_key: str,
    resolve_ticker: Callable[[str, AssetType], str | None] | None = None,
) -> dict[str, Any]:
    """Route a House PTR to its extractor and serialize its rows to silver Parquet.

    `bronze_key` (`bronze/house/year=<year>/<doc_id>.<ext>`) supplies the
    `chamber`, `year` and `doc_id` used both for routing (`route_doc_id`
    classifies `doc_id` as `"digital"` or `"scanned"` with no manual
    classification) and for the output silver keys (`silver_key`), so the
    doc id never has to be threaded through as a separate argument.

    `resolve_ticker(asset_description, asset_type)`, when given, is called
    for every transaction row whose `ticker` is still null and whose
    `asset_type` is stock/ETF, to fill it from the row's `asset_description`
    (see module docstring); every other row's ticker is left exactly as the
    extractor produced it. Omitting it (the default) performs no resolution
    at all, e.g. for callers/tests with no OpenFIGI/EDGAR access.

    Returns `{"kind": ..., "filings": {"key": ..., "bytes": ...},
    "transactions": {"key": ..., "bytes": ...}}`: one Hive-partitioned
    Parquet part file per silver table, at one part per `doc_id` (ADR 0008).
    The actual S3 write is the caller's job, as with every other stage here.
    Raises `DocIdMismatchError` if the extracted `Filing.doc_id` disagrees
    with the bronze key's own doc id, rather than silently writing a row
    under a partition path that disagrees with the doc id inside it.
    """
    chamber, year, doc_id = _parse_bronze_key(bronze_key)
    kind = route_doc_id(doc_id)
    extraction = _EXTRACTORS[kind](pdf_bytes, bronze_key=bronze_key)

    if extraction.filing.doc_id != doc_id:
        raise DocIdMismatchError(
            f"{bronze_key}: filing doc_id {extraction.filing.doc_id!r} "
            f"disagrees with the bronze key's doc id {doc_id!r}"
        )

    transaction_rows = []
    for transaction in extraction.transactions:
        row = transaction_row(transaction)
        if (
            row["ticker"] is None
            and resolve_ticker is not None
            and transaction.asset_type in TICKER_ASSET_TYPES
        ):
            row["ticker"] = resolve_ticker(transaction.asset_description, transaction.asset_type)
        transaction_rows.append(row)

    return {
        "kind": kind,
        "filings": {
            "key": silver_key(FILINGS_TABLE, chamber, year, doc_id),
            "bytes": _parquet_bytes([_filing_row(extraction.filing)], _FILING_SCHEMA),
        },
        "transactions": {
            "key": silver_key(TRANSACTIONS_TABLE, chamber, year, doc_id),
            "bytes": _parquet_bytes(transaction_rows, _TRANSACTION_SCHEMA),
        },
    }
