"""Digital House PDF extractor: a text-layer PTR into silver `Filing`/`Transaction` rows.

Follows ADR 0003. `pypdf` extracts the text layer; each Transaction is
located by its transaction line, the `<type> <date> <date> <$range>` anchor
(`_ANCHOR_RE`), and its other fields are read by walking away from that
anchor: backward for the owner code and asset description, forward for the
labelled lines (`Filing Status:`, `Subholding Of:`, `Description:`).

pypdf garbles the bold labels. With pypdf 6 every character after a word's
first comes out as NUL (`F\\x00\\x00\\x00\\x00\\x00 S\\x00\\x00\\x00\\x00\\x00:`
for `Filing Status:`); earlier versions inserted stray whitespace instead.
So a candidate line is only accepted as a label once it matches the label's
characters with all whitespace ignored and NUL standing in for any single
character (`_label_pattern`). A line that doesn't match any label ends the
forward walk, so a missing optional line (most often `Subholding Of:`)
leaves its field null at `LOW_CONFIDENCE` rather than reading whatever
line happens to sit at that offset. Section headers are never used as
anchors; only the repeated column header and the `Filing ID #` page footer
are dropped, so a Transaction split across a page break reads as one.

Two source quirks are kept rather than corrected: a notification date
printed before its transaction date is stored exactly as printed, and a
`Description:` value wrapped onto a second line would be read as the start
of the next line's asset description (no fixture has one yet).
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from datetime import date, datetime

from pypdf import PdfReader

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

EXTRACTOR_NAME = "house-digital-pdf"

# Confidence of a field the extractor looked for but didn't find.
LOW_CONFIDENCE = 0.0

# Optional labelled lines that follow a transaction line, by Transaction field.
LABELS = {
    "filing_status": "Filing Status:",
    "sub_owner": "Subholding Of:",
    "description": "Description:",
}

# The column header pypdf repeats at the top of every page of the table.
_COLUMN_HEADER = (
    "ID Owner Asset Transaction",
    "Type",
    "Date Notification",
    "Date",
    "Amount Cap.",
    "Gains >",
    "$200?",
)
_TABLE_END_PREFIX = "* For the complete list of asset type abbreviations"
_PAGE_FOOTER_RE = re.compile(r"^Filing ID #(?P<doc_id>\d+)$")

_ANCHOR_RE = re.compile(
    r"(?:^|\s)(?P<type>S \(partial\)|P|S|E)\s+"
    r"(?P<transaction_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<notification_date>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<amount>\S.*)$",
    re.IGNORECASE,
)
_OWNER_RE = re.compile(r"^(?P<owner>SP|JT|DC)\s+")
_ASSET_TYPE_CODE_RE = re.compile(r"\[(?P<code>[A-Z0-9]{2})\]$")
_NAME_RE = re.compile(r"^Name:\s*(?P<name>.+)$", re.MULTILINE)
_SIGNED_RE = re.compile(r"Digitally Signed:\s*.+?,\s*(?P<date>\d{2}/\d{2}/\d{4})")

_RANGE_RE = re.compile(r"^\$(?P<min>[\d,]+)\s*-\s*\$(?P<max>[\d,]+)$")
_OVER_RE = re.compile(r"Over \$(?P<min>[\d,]+)$")

_OWNERS = {"": Owner.SELF, "SP": Owner.SPOUSE, "JT": Owner.JOINT, "DC": Owner.DEPENDENT_CHILD}
_TRANSACTION_TYPES = {
    "P": TransactionType.PURCHASE,
    "S": TransactionType.SALE_FULL,
    "S (PARTIAL)": TransactionType.SALE_PARTIAL,
    "E": TransactionType.EXCHANGE,
}
# House asset-type codes (fd.house.gov/reference/asset-type-codes.aspx) the
# silver enum distinguishes; every other code is `OTHER`.
_ASSET_TYPES = {
    "ST": AssetType.STOCK,
    "EF": AssetType.ETF,
    "MF": AssetType.MUTUAL_FUND,
    "GS": AssetType.BOND,
    "CS": AssetType.BOND,
    "OP": AssetType.OPTION,
    "CT": AssetType.CRYPTOCURRENCY,
    "RP": AssetType.REAL_ESTATE,
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
    return re.compile(r"^\s*" + r"\s*".join(parts) + r"\s*(?P<value>.*)$")


_LABEL_PATTERNS = {name: _label_pattern(label) for name, label in LABELS.items()}


def _match_label(line: str) -> tuple[str, str | None] | None:
    for name, pattern in _LABEL_PATTERNS.items():
        match = pattern.match(line)
        if match:
            return name, match.group("value").strip() or None
    return None


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%m/%d/%Y").date()


def _dollars(raw: str) -> int:
    return int(raw.replace(",", ""))


def parse_value_range(raw: str) -> ValueRange | None:
    """Parse a House amount column (`$1,001 - $15,000`, `Over $50,000,000`).

    An open-ended `Over $X` bracket starts one dollar above `X`, matching how
    the closed brackets start (`$1,001`), and has no upper bound. Returns
    None for text that isn't a complete amount.
    """
    raw = " ".join(raw.split())
    match = _RANGE_RE.match(raw)
    if match:
        return ValueRange(_dollars(match.group("min")), _dollars(match.group("max")))
    match = _OVER_RE.search(raw)
    if match:
        return ValueRange(_dollars(match.group("min")) + 1, math.inf)
    return None


def _table_lines(lines: list[str]) -> list[str]:
    """The transaction table's lines, with page headers and footers removed."""
    header = list(_COLUMN_HEADER)
    table: list[str] = []
    started = False
    i = 0
    while i < len(lines):
        if lines[i : i + len(header)] == header:
            started = True
            i += len(header)
            continue
        line = lines[i]
        i += 1
        if not started or _PAGE_FOOTER_RE.match(line):
            continue
        if line.startswith(_TABLE_END_PREFIX):
            break
        table.append(line)
    if not started:
        raise ValueError("no transaction table column header found")
    return table


def _asset_fields(asset_text: str) -> tuple[str, str, AssetType, float]:
    """Split an asset cell into (owner_raw, description, asset_type, asset_type confidence)."""
    owner_match = _OWNER_RE.match(asset_text)
    owner_raw = owner_match.group("owner") if owner_match else ""
    description = asset_text[owner_match.end() :] if owner_match else asset_text
    code_match = _ASSET_TYPE_CODE_RE.search(description)
    if code_match is None:
        return owner_raw, description, AssetType.OTHER, LOW_CONFIDENCE
    return owner_raw, description, _ASSET_TYPES.get(code_match.group("code"), AssetType.OTHER), 1.0


def extract_digital(pdf_bytes: bytes, *, bronze_key: str) -> DigitalExtraction:
    """Extract a digital House PTR's `Filing` and `Transaction` rows.

    `pdf_bytes` is the bronze object at `bronze_key`, which is recorded as
    every row's provenance. Raises ValueError when a field the silver schema
    requires (filer name, filing date, doc id, a transaction's value range)
    can't be read, rather than writing a guessed row.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() for page in reader.pages)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    doc_id = next((m.group("doc_id") for line in lines if (m := _PAGE_FOOTER_RE.match(line))), None)
    name = _NAME_RE.search(text)
    signed = _SIGNED_RE.search(text)
    if doc_id is None or name is None or signed is None:
        raise ValueError(f"{bronze_key}: missing Filing ID, Name or Digitally Signed line")
    filing_date = _parse_date(signed.group("date"))
    provenance = Provenance(bronze_key=bronze_key, extractor=EXTRACTOR_NAME)
    filing = Filing(
        doc_id=doc_id,
        chamber=Chamber.HOUSE,
        filer_name=name.group("name").strip(),
        filing_date=filing_date,
        year=filing_date.year,
        confidence=1.0,
        provenance=provenance,
    )

    table = _table_lines(lines)
    transactions: list[Transaction] = []
    block_start = 0
    i = 0
    while i < len(table):
        anchor = _ANCHOR_RE.search(table[i])
        if anchor is None:
            i += 1
            continue

        asset_lines = [*table[block_start:i], table[i][: anchor.start()]]
        asset_text = " ".join(" ".join(asset_lines).split())
        owner_raw, asset_description, asset_type, asset_type_confidence = _asset_fields(asset_text)

        amount = anchor.group("amount")
        i += 1
        value_range = parse_value_range(amount)
        if value_range is None and i < len(table):
            value_range = parse_value_range(f"{amount} {table[i]}")
            i += 1
        if value_range is None:
            raise ValueError(f"{bronze_key}: unreadable amount {amount!r}")

        labelled: dict[str, str | None] = {}
        while i < len(table) and (label := _match_label(table[i])) is not None:
            labelled.setdefault(*label)
            i += 1
        block_start = i

        field_confidence = {
            name: 1.0 if labelled.get(name) is not None else LOW_CONFIDENCE for name in LABELS
        }
        field_confidence["asset_type"] = asset_type_confidence
        type_raw = anchor.group("type")
        transactions.append(
            Transaction(
                doc_id=doc_id,
                line_no=len(transactions) + 1,
                owner=_OWNERS[owner_raw],
                owner_raw=owner_raw,
                transaction_type=_TRANSACTION_TYPES[type_raw.upper()],
                transaction_type_raw=type_raw,
                asset_type=asset_type,
                asset_description=asset_description,
                transaction_date=_parse_date(anchor.group("transaction_date")),
                filing_date=filing_date,
                value_range=value_range,
                confidence=1.0,
                provenance=provenance,
                notification_date=_parse_date(anchor.group("notification_date")),
                filing_status=labelled.get("filing_status"),
                sub_owner=labelled.get("sub_owner"),
                description=labelled.get("description"),
                field_confidence=field_confidence,
            )
        )

    return DigitalExtraction(filing=filing, transactions=transactions)
