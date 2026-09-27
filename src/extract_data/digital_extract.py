"""Digital House PDF extractor: a text-layer PTR into silver `Filing`/`Transaction` rows.

Follows ADR 0003. `pypdf` reads the text layer as positioned chunks, which
are rebuilt into visual lines (one per baseline, left to right). Each
Transaction is located by its transaction line, the
`<type> <date> <date> <$range>` anchor (`_ANCHOR_RE`), which shares its
visual line with the first line of the asset cell. The other fields are
read by walking away from that anchor, within the anchor's own table row:
the asset text around it, then the labelled lines below it
(`Filing Status:`, `Subholding Of:`, `Description:`, ...).

Rows are delimited by vertical whitespace, not by text. Lines inside a
row sit at most ~21pt apart, rows at least ~26pt (`_ROW_GAP`), measured over
1,678 rows of 57 sampled 2025 filings. A wrapped label value (a long
`Comments:`) therefore stays with its own row instead of leaking into the
next row's asset description. A row a page break splits carries on past
the next page's column header without an anchor of its own, and is joined
back onto the row it continues.

Older forms (2020-2022) come out with some capitals mapped to lowercase
(`Filing Id`, `[gS]`, `(AAl)`), so every structural match is
case-insensitive; the text itself is kept as pypdf reads it.

pypdf garbles the bold labels. With pypdf 6 every character after a word's
first comes out as NUL (`F\\x00\\x00\\x00\\x00\\x00 S\\x00\\x00\\x00\\x00\\x00:`
for `Filing Status:`); earlier versions inserted stray whitespace instead.
So a line is only accepted as a label once it matches the label's
characters with all whitespace ignored and NUL standing in for any single
character (`_label_pattern`). A label that isn't in a row leaves its field
null, never filled from whatever line sits at that offset. Since the row's
lines are all accounted for, that null is confident: the form has no such
line. `LOW_CONFIDENCE` is kept for what is there but unreadable (a label
with no value, an asset with no type code), which is what a fallback stage
may try to recover. Section headers are never used as anchors.

A notification date printed before its transaction date (a known source
bug) is kept exactly as printed, not corrected.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from pypdf import PageObject, PdfReader

from extract_data import _house_form
from shared.schema import (
    AssetType,
    Chamber,
    Filing,
    Provenance,
    Transaction,
    TransactionType,
    ValueRange,
)

EXTRACTOR_NAME = "house-digital-pdf"

# Confidence of a field read from a validated label or anchor.
FULL_CONFIDENCE = 1.0
# Confidence of a field present in the source but not readable.
LOW_CONFIDENCE = 0.0

# Optional labelled lines under a transaction line, by Transaction field.
_LABELS = {
    "filing_status": "Filing Status:",
    "sub_owner": "Subholding Of:",
    "description": "Description:",
}
# Labelled lines recognized so their text isn't read as another field, but
# with no silver field yet: they are not stored.
_UNSTORED_LABELS = {
    "location": "Location:",
    "comments": "Comments:",
}

# Font the 2021 form draws its cap-gains checkboxes in, as glyph text.
_CHECKBOX_FONT_SUFFIX = "Marlett"

# Vertical gap, in points, above which the next line starts a new table row.
_ROW_GAP = 23.5

# Last line of the column header repeated at the top of every table page.
_COLUMN_HEADER_END = "$200?"
_TABLE_END_PREFIX = "* For the complete list of asset type abbreviations"
_PAGE_FOOTER_RE = re.compile(r"^Filing ID #(?P<doc_id>\d+)$", re.IGNORECASE)

_ANCHOR_RE = re.compile(
    r"(?:^|\s)(?P<type>S \(partial\)|P|S|E)\s+"
    r"(?P<transaction_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<notification_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<amount>\S.*)$",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"^Name:\s*(?P<name>.+)$", re.MULTILINE | re.IGNORECASE)
_SIGNED_RE = re.compile(r"Digitally Signed:\s*.+?,\s*(?P<date>\d{2}/\d{2}/\d{4})")

# A line under the transaction line ending in the amount's upper bound,
# after any wrapped asset text sharing that visual line.
_AMOUNT_TAIL_RE = re.compile(r"^(?P<asset>.*?)\s*(?P<max>\$[\d,]+)$")
_RANGE_RE = re.compile(r"^\$(?P<min>[\d,]+)\s*-\s*\$(?P<max>[\d,]+)$")
_OVER_RE = re.compile(r"Over \$(?P<min>[\d,]+)$")
# A literal amount under the $1,000 bracket-reporting threshold, printed
# instead of a bracket (e.g. "$9.00").
_LITERAL_RE = re.compile(r"^\$(?P<amount>[\d,]+(?:\.\d+)?)$")

_TRANSACTION_TYPES = {
    "P": TransactionType.PURCHASE,
    "S": TransactionType.SALE_FULL,
    "S (PARTIAL)": TransactionType.SALE_PARTIAL,
    "E": TransactionType.EXCHANGE,
}


@dataclass(frozen=True)
class DigitalExtraction:
    """The silver rows extracted from one digital House PTR."""

    filing: Filing
    transactions: list[Transaction]


def _label_pattern(label: str) -> re.Pattern[str]:
    parts = [
        f"[{re.escape(c)}\x00]" if c.isalnum() else re.escape(c) for c in label if not c.isspace()
    ]
    # Case-insensitive: the 2021 form's small-caps labels come out mixed-case.
    return re.compile(r"^\s*" + r"\s*".join(parts) + r"\s*(?P<value>.*)$", re.IGNORECASE)


_LABEL_PATTERNS = {
    name: _label_pattern(label) for name, label in {**_LABELS, **_UNSTORED_LABELS}.items()
}


def _match_label(line: str) -> tuple[str, str] | None:
    for name, pattern in _LABEL_PATTERNS.items():
        match = pattern.match(line)
        if match:
            return name, match.group("value").strip()
    return None


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%m/%d/%Y").date()


def _dollars(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_value_range(raw: str) -> ValueRange | None:
    """Parse a House amount column (`$1,001 - $15,000`, `Over $50,000,000`).

    An open-ended `Over $X` bracket starts one dollar above `X`, matching how
    the closed brackets start (`$1,001`), and has a null upper bound. A bare
    `$X[.XX]` (under the $1,000 bracket-reporting threshold) is its own
    min and max. Returns None for text that isn't a complete amount.
    """
    raw = " ".join(raw.split())
    match = _RANGE_RE.match(raw)
    if match:
        return ValueRange(_dollars(match.group("min")), _dollars(match.group("max")))
    match = _OVER_RE.search(raw)
    if match:
        return ValueRange(_dollars(match.group("min")) + 1, None)
    match = _LITERAL_RE.match(raw)
    if match:
        amount = _dollars(match.group("amount"))
        return ValueRange(amount, amount)
    return None


def _visual_lines(page: PageObject) -> list[tuple[float, str]]:
    """A page's text as `(baseline y, text)` lines, top to bottom."""
    chunks: dict[float, list[tuple[float, str]]] = defaultdict(list)

    def visit(text, cm, tm, font, _size):
        # pypdf also flushes the whole page's text once with no font and an
        # identity matrix; only real, positioned chunks are kept.
        if font is None or not text.strip():
            return
        if str(font.get("/BaseFont", "")).endswith(_CHECKBOX_FONT_SUFFIX):
            return
        y = round(tm[5] * cm[3] + cm[5], 1)
        chunks[y].append((tm[4] * cm[0] + cm[4], text))

    page.extract_text(visitor_text=visit)
    # Sort by x only: chunks of one text object can share an x, and then
    # only their emission order is right.
    return [
        (y, " ".join(" ".join(text for _, text in sorted(chunks[y], key=lambda c: c[0])).split()))
        for y in sorted(chunks, reverse=True)
    ]


def _table_rows(pages: list[list[tuple[float, str]]]) -> list[list[str]]:
    """Split the transaction table into rows, one per transaction line.

    A run of lines with no transaction line (a row's labels pushed onto the
    next page, or its wrapped asset text) continues the row above it.
    """
    if not any(text == _COLUMN_HEADER_END for lines in pages for _, text in lines):
        raise ValueError("no transaction table column header found")
    segments: list[list[str]] = []
    for lines in pages:
        texts = [text for _, text in lines]
        if _COLUMN_HEADER_END not in texts:
            continue
        previous_y = None
        for y, text in lines[texts.index(_COLUMN_HEADER_END) + 1 :]:
            if text.lower().startswith(_TABLE_END_PREFIX.lower()):
                break
            if _PAGE_FOOTER_RE.match(text):
                continue
            if previous_y is None or previous_y - y > _ROW_GAP:
                segments.append([])
            segments[-1].append(text)
            previous_y = y

    rows: list[list[str]] = []
    for segment in segments:
        anchors = sum(1 for text in segment if _ANCHOR_RE.search(text))
        if anchors > 1:
            # Never seen in the sampled filings; failing beats guessing
            # which lines belong to which transaction.
            raise ValueError(f"one table row holds {anchors} transaction lines: {segment[:3]!r}")
        if anchors == 0 and rows:
            rows[-1].extend(segment)
        elif anchors == 1:
            rows.append(segment)
    return rows


@dataclass(frozen=True)
class _AssetCell:
    owner_raw: str
    description: str
    asset_type: AssetType
    asset_type_confidence: float
    ticker: str | None


def _asset_cell(asset_lines: list[str]) -> _AssetCell:
    """Split an asset cell's lines into its owner code, description, asset type and ticker.

    `ticker` is the filer's own printed symbol, kept only for stock/ETF
    lines: the same parenthesized shape holds a CUSIP or other identifier
    for every other asset type. It is never resolved or guessed here — a
    filing with no parenthesized symbol, or a non-stock/ETF asset, leaves it
    null for the ticker-resolution cascade (#39) to fill by asset name.
    """
    asset_text = " ".join(" ".join(asset_lines).split())
    owner_match = _house_form.OWNER_RE.match(asset_text)
    owner_raw = owner_match.group("owner") if owner_match else ""
    description = asset_text[owner_match.end() :] if owner_match else asset_text
    code_match = _house_form.ASSET_TYPE_CODE_RE.search(description)
    if code_match is None:
        return _AssetCell(owner_raw, description, AssetType.OTHER, LOW_CONFIDENCE, None)
    asset_type = _house_form.ASSET_TYPES.get(code_match.group("code").upper(), AssetType.OTHER)
    ticker = None
    if asset_type in (AssetType.STOCK, AssetType.ETF):
        symbol_match = _house_form.PRINTED_SYMBOL_RE.search(description)
        if symbol_match is not None:
            ticker = symbol_match.group(1).upper()
    return _AssetCell(owner_raw, description, asset_type, FULL_CONFIDENCE, ticker)


def _parse_filing(text: str, bronze_key: str) -> Filing:
    doc_id = next(
        (m.group("doc_id") for line in text.splitlines() if (m := _PAGE_FOOTER_RE.match(line))),
        None,
    )
    name = _NAME_RE.search(text)
    signed = _SIGNED_RE.search(text)
    if doc_id is None or name is None or signed is None:
        raise ValueError(f"{bronze_key}: missing Filing ID, Name or Digitally Signed line")
    filing_date = _parse_date(signed.group("date"))
    return Filing(
        doc_id=doc_id,
        chamber=Chamber.HOUSE,
        filer_name=name.group("name").strip(),
        filing_date=filing_date,
        year=filing_date.year,
        confidence=FULL_CONFIDENCE,
        provenance=Provenance(bronze_key=bronze_key, extractor=EXTRACTOR_NAME),
    )


def _parse_row(row: list[str], filing: Filing, line_no: int) -> Transaction:
    """One Transaction from a table row holding exactly one transaction line."""
    anchor_at = next(i for i, text in enumerate(row) if _ANCHOR_RE.search(text))
    anchor = _ANCHOR_RE.search(row[anchor_at])
    asset_lines = [*row[:anchor_at], row[anchor_at][: anchor.start()]]
    amount = anchor.group("amount")
    value_range = parse_value_range(amount)

    # Under the transaction line: wrapped asset text (the amount's upper
    # bound may share its line), then labelled lines, each possibly wrapped.
    labelled: dict[str, list[str]] = {}
    current: list[str] | None = None
    for text in row[anchor_at + 1 :]:
        label = _match_label(text)
        if label is not None:
            name, value = label
            if name in labelled:
                current = []  # a repeated label's text is dropped, not merged
            else:
                current = labelled[name] = [value]
            continue
        if current is not None:
            current.append(text)
            continue
        tail = _AMOUNT_TAIL_RE.match(text) if value_range is None else None
        if tail is not None:
            value_range = parse_value_range(f"{amount} {tail.group('max')}")
            text = tail.group("asset")
        asset_lines.append(text)
    if value_range is None:
        raise ValueError(f"{filing.provenance.bronze_key}: unreadable amount {amount!r}")

    values = {name: " ".join(" ".join(parts).split()) or None for name, parts in labelled.items()}
    asset = _asset_cell(asset_lines)
    # An absent label is a confident null; a label with no value is not.
    field_confidence = {
        name: LOW_CONFIDENCE if name in labelled and values[name] is None else FULL_CONFIDENCE
        for name in _LABELS
    }
    field_confidence["asset_type"] = asset.asset_type_confidence
    type_raw = anchor.group("type")
    return Transaction(
        doc_id=filing.doc_id,
        line_no=line_no,
        owner=_house_form.OWNERS[asset.owner_raw],
        owner_raw=asset.owner_raw,
        transaction_type=_TRANSACTION_TYPES[type_raw.upper()],
        transaction_type_raw=type_raw,
        asset_type=asset.asset_type,
        asset_description=asset.description,
        transaction_date=_parse_date(anchor.group("transaction_date")),
        filing_date=filing.filing_date,
        value_range=value_range,
        confidence=min(field_confidence.values()),
        provenance=filing.provenance,
        ticker=asset.ticker,
        notification_date=_parse_date(anchor.group("notification_date")),
        filing_status=values.get("filing_status"),
        sub_owner=values.get("sub_owner"),
        description=values.get("description"),
        field_confidence=field_confidence,
    )


def extract_digital(pdf_bytes: bytes, *, bronze_key: str) -> DigitalExtraction:
    """Extract a digital House PTR's `Filing` and `Transaction` rows.

    `pdf_bytes` is the bronze object at `bronze_key`, which is recorded as
    every row's provenance. Raises ValueError when a field the silver schema
    requires (filer name, filing date, doc id, a transaction's value range)
    can't be read, or the table can't be split into rows, rather than
    writing a guessed row.
    """
    pages = [_visual_lines(page) for page in PdfReader(io.BytesIO(pdf_bytes)).pages]
    filing = _parse_filing("\n".join(text for lines in pages for _, text in lines), bronze_key)
    rows = _table_rows(pages)
    transactions = [_parse_row(row, filing, line_no) for line_no, row in enumerate(rows, 1)]
    return DigitalExtraction(filing=filing, transactions=transactions)
