"""Senate PTR HTML extractor: eFD's structured print view into silver `Filing`/`Transaction` rows.

Unlike a House PTR (a text-layer PDF needing a positional walk, ADR 0003), a
Senate `/ptr/` filing page is already a real, structured `<table>` — parsed
here with `BeautifulSoup`, not regex-anchored text. There is no digital/
scanned duality either: only clean HTML `/ptr/` pages are collected
(`stages.senate_collect`), so this is the one and only Senate extractor.

Per ADR 0013: the page carries no doc id of its own anywhere in its HTML (a
House PDF's footer prints `Filing ID #<doc_id>`; Senate's UUID exists only in
the eFD search result's URL, already the bronze key's `doc_id`), so `doc_id`
is taken as given, never cross-checked against the page's own content. An
`Exchange` row's asset cell holds two lines of text (the asset given up, then
the asset received) with no structured split in the source; the given-up
asset lands in `asset_description` and the received asset's text is kept
verbatim in `description` — the same field a Purchase/Sale row uses for its
`Option Type`/`Strike price`/`Expires` block, or (an `Other`/private-stock
row) its `Company:`/`Description:` pair, confirmed against a 40-filing
real-world sample (`eval/senate_fixtures/`) to sometimes carry *two*
`text-muted` divs on one row — both are kept, joined, never just the first
with the second silently dropped. `notification_date`, `filing_status` and
`sub_owner` have no structured source on this page at all and stay null,
matching ADR 0002's null-over-guessed precedent; the free-text `Comment`
column is dropped entirely, even when it happens to mention a date.

Every field this extractor does read comes from a real HTML element, never a
positional guess, so a successful parse is always `FULL_CONFIDENCE` (unlike
the House PDF walk's per-field confidence) and `field_confidence` is left
empty. An owner or transaction-type string this extractor doesn't recognize
raises rather than silently miscategorizing a row; an unrecognized asset-type
string falls back to `AssetType.OTHER`, mirroring how the House extractor
treats an unknown asset-type code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup
from bs4.element import Tag

from capitol_lake.schema import (
    AssetType,
    Chamber,
    Filing,
    Owner,
    Provenance,
    Transaction,
    TransactionType,
)
from capitol_lake.stages.digital_extract import parse_value_range

EXTRACTOR_NAME = "senate-html-ptr"

# Every field here comes from a real HTML element, never a positional guess.
FULL_CONFIDENCE = 1.0

_HONORIFIC_RE = re.compile(r"^(?:Mr|Mrs|Ms|Miss|Dr|Hon|Sen|Rep)\.\s+", re.IGNORECASE)
_PAREN_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")
_FILED_RE = re.compile(r"Filed\s+(?P<date>\d{2}/\d{2}/\d{4})")
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

_TRANSACTIONS_TABLE_COLUMNS = 9

# Only the Asset Type strings observed in sampled Senate PTRs whose text
# doesn't already match an `AssetType` value once normalized (e.g. "Stock"
# normalizes straight to "stock" = `AssetType.STOCK`, needing no entry here).
# Anything else falls back to OTHER, exactly like House's asset-type-code
# fallback (`_house_form.ASSET_TYPES`).
_ASSET_TYPE_ALIASES = {
    "stock_option": AssetType.OPTION,
    "corporate_bond": AssetType.BOND,
    "municipal_security": AssetType.BOND,
    "government_bond": AssetType.BOND,
}


class SenateFilingFormatError(ValueError):
    """A Senate PTR page doesn't have the structure this extractor expects."""


class UnknownSenateOwnerError(ValueError):
    """A transaction row's Owner column doesn't match any known `Owner` value."""


class UnknownSenateTransactionTypeError(ValueError):
    """A transaction row's Type column doesn't match any known `TransactionType` value."""


@dataclass(frozen=True)
class SenateExtraction:
    """The silver rows extracted from one Senate `/ptr/` filing page."""

    filing: Filing
    transactions: list[Transaction]


def _normalize(raw: str) -> str:
    return _NORMALIZE_RE.sub("_", raw.strip().lower()).strip("_")


def _flatten_text(tag: Tag) -> str:
    for br in tag.find_all("br"):
        br.replace_with(" ")
    return " ".join(tag.get_text(" ", strip=True).split())


def _owner_from_raw(raw: str) -> Owner:
    try:
        return Owner(_normalize(raw))
    except ValueError:
        raise UnknownSenateOwnerError(f"unrecognized Senate owner: {raw!r}") from None


def _transaction_type_from_raw(raw: str) -> TransactionType:
    try:
        return TransactionType(_normalize(raw))
    except ValueError:
        raise UnknownSenateTransactionTypeError(
            f"unrecognized Senate transaction type: {raw!r}"
        ) from None


def _asset_type_from_raw(raw: str) -> AssetType:
    normalized = _normalize(raw)
    try:
        return AssetType(normalized)
    except ValueError:
        return _ASSET_TYPE_ALIASES.get(normalized, AssetType.OTHER)


def _parse_filer_name(soup: BeautifulSoup) -> str:
    header = soup.find("h2", class_="filedReport")
    if header is None:
        raise SenateFilingFormatError("no h2.filedReport header found")
    raw = " ".join(header.get_text().split())
    raw = _PAREN_SUFFIX_RE.sub("", raw)
    name = _HONORIFIC_RE.sub("", raw).strip()
    if not name:
        raise SenateFilingFormatError(f"filer name is empty once stripped: {raw!r}")
    return name


def _parse_filing_date(soup: BeautifulSoup) -> date:
    muted = soup.find("p", class_="muted")
    text = muted.get_text(" ", strip=True) if muted is not None else ""
    match = _FILED_RE.search(text)
    if match is None:
        raise SenateFilingFormatError("no 'Filed MM/DD/YYYY' line found")
    return datetime.strptime(match.group("date"), "%m/%d/%Y").date()


def _find_transactions_table(soup: BeautifulSoup) -> Tag:
    table = soup.find("table", class_="table-striped")
    if table is None:
        raise SenateFilingFormatError("no table.table-striped transactions table found")
    return table


def _parse_asset_cell(cell: Tag) -> tuple[str, str | None]:
    """Split an asset cell into its primary description and any secondary text.

    Every `text-muted` div in the cell is read separately, then removed, so
    none of them leak into the primary line: an Option row has one (Option
    Type/Strike price/Expires), a private-stock (`Other` asset type) row can
    have two (`Company:` and `Description:`, confirmed against real sampled
    filings, eval#40-senate) — all are kept, joined, rather than only the
    first with the rest silently dropped. A row with no `text-muted` div at
    all falls back to its second line, if any (an Exchange row's
    "(Received)" leg). Either way the first remaining line is the primary
    `asset_description`.
    """
    muted_divs = cell.find_all("div", class_="text-muted")
    secondary_parts = [_flatten_text(div) for div in muted_divs]
    for div in muted_divs:
        div.decompose()
    for br in cell.find_all("br"):
        br.replace_with("\n")
    # A stray double space in the source's own data (confirmed real,
    # eval#40-senate) must not survive into asset_description verbatim -
    # every other field this extractor reads is already whitespace-collapsed
    # by `get_text(strip=True)`; this is the one field built from raw text.
    lines = [" ".join(line.split()) for line in cell.get_text().split("\n") if line.strip()]
    if not lines:
        raise SenateFilingFormatError("asset cell has no description text")
    if not secondary_parts and len(lines) > 1:
        secondary_parts = [" ".join(lines[1:])]
    return lines[0], " ".join(secondary_parts) if secondary_parts else None


def _parse_row(row: Tag, filing: Filing) -> Transaction:
    cells = row.find_all("td")
    if len(cells) != _TRANSACTIONS_TABLE_COLUMNS:
        raise SenateFilingFormatError(
            f"expected {_TRANSACTIONS_TABLE_COLUMNS} transaction columns, got {len(cells)}"
        )
    (
        line_no_cell,
        date_cell,
        owner_cell,
        ticker_cell,
        asset_cell,
        asset_type_cell,
        type_cell,
        amount_cell,
        _comment_cell,
    ) = cells

    line_no = int(line_no_cell.get_text(strip=True))
    transaction_date = datetime.strptime(date_cell.get_text(strip=True), "%m/%d/%Y").date()
    owner_raw = owner_cell.get_text(strip=True)
    ticker_raw = ticker_cell.get_text(strip=True)
    ticker = ticker_raw.upper() if ticker_raw and ticker_raw != "--" else None
    asset_description, description = _parse_asset_cell(asset_cell)
    type_raw = type_cell.get_text(strip=True)
    amount_raw = amount_cell.get_text(strip=True)
    value_range = parse_value_range(amount_raw)
    if value_range is None:
        raise SenateFilingFormatError(
            f"{filing.provenance.bronze_key}: unreadable amount {amount_raw!r}"
        )

    return Transaction(
        doc_id=filing.doc_id,
        line_no=line_no,
        owner=_owner_from_raw(owner_raw),
        owner_raw=owner_raw,
        transaction_type=_transaction_type_from_raw(type_raw),
        transaction_type_raw=type_raw,
        asset_type=_asset_type_from_raw(asset_type_cell.get_text(strip=True)),
        asset_description=asset_description,
        transaction_date=transaction_date,
        filing_date=filing.filing_date,
        value_range=value_range,
        confidence=FULL_CONFIDENCE,
        provenance=filing.provenance,
        ticker=ticker,
        description=description,
    )


def extract_senate_html(html_bytes: bytes, *, bronze_key: str, doc_id: str) -> SenateExtraction:
    """Extract a Senate `/ptr/` filing page's `Filing` and `Transaction` rows.

    `html_bytes` is the bronze object at `bronze_key`. `doc_id` is the bronze
    key's own doc id (per ADR 0013, there is nothing on the page itself to
    read it from or cross-check it against). A page with no transactions
    table row is a valid, empty-transactions `Filing` — the Senate print view
    always renders its (possibly zero-row) table, so an empty table means the
    filer reported nothing, not that parsing failed. Raises
    `SenateFilingFormatError` when the page doesn't have the structure this
    extractor expects, `UnknownSenateOwnerError`/`UnknownSenateTransactionTypeError`
    when a row's Owner/Type text doesn't match a known value, rather than
    writing a guessed or miscategorized row.
    """
    soup = BeautifulSoup(html_bytes, "lxml")
    filing_date = _parse_filing_date(soup)
    filing = Filing(
        doc_id=doc_id,
        chamber=Chamber.SENATE,
        filer_name=_parse_filer_name(soup),
        filing_date=filing_date,
        year=filing_date.year,
        confidence=FULL_CONFIDENCE,
        provenance=Provenance(bronze_key=bronze_key, extractor=EXTRACTOR_NAME),
    )
    table = _find_transactions_table(soup)
    body = table.find("tbody")
    rows = body.find_all("tr") if body is not None else []
    transactions = [_parse_row(row, filing) for row in rows]
    return SenateExtraction(filing=filing, transactions=transactions)
