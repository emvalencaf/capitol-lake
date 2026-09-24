"""Scanned House PDF extractor: full-page Tesseract OCR into silver rows.

Follows ADR 0002 (and its #37 addendum). A scanned PTR has no text layer —
`pypdfium2` rasterizes each page and `pytesseract` OCRs it. The paper form's
mediabox is always portrait but its printed content is landscape (the form
was fed sideways through the scanner), so every page is rotated 90 degrees
one way or the other before OCR; the direction is decided once from page 1
(whichever of the two candidate rotations yields more of the form's own
header words) and reused for every page of the filing, since a single scan
run doesn't change orientation partway through.

Filer name and the Legislative Resource Center's date-received stamp OCR
reliably from the full page and need no table structure. The transaction
table does not: `transaction_type` and the dollar-amount columns are
hand/typed checkbox grids (a checkmark or an `X` in a lettered box), and
full-page OCR of a checkbox is noise, not a value — the same reason ADR 0002
declined zonal OCR for `transaction_type`, now confirmed to apply to
`value_range` too (its addendum). Both are always null here.

The asset-name and date-of-transaction columns are typed/handwritten text,
not checkboxes, so they're attempted: each page is split into three
horizontal bands by a fixed fraction of its (rotated) width/height,
calibrated against sampled real scanned PTRs (`_ASSET_COLUMN_RATIO`,
`_AMOUNT_COLUMN_RATIO`, `_TABLE_TOP_RATIO`). This is a coarser, cheaper
assumption than the zonal OCR ADR 0002 declined — it only has to isolate a
wide, forgiving text column, not resolve which of eleven adjacent checkbox
letters is marked, so drifting a few percent off doesn't change what a
value *means*, only how much stray noise rides along with it. The asset
column and the two-date column are each OCR'd once per page (not once per
row), and rows are paired across the two crops by vertical order, not
coordinate matching, since the two crops don't share a coordinate space
after grid-line removal shifts pixels.

Grid lines wreck OCR worse than the checkboxes do: a table border touching
a digit merges into one unrecognizable glyph. `_remove_gridlines` blanks
any row or column of pixels that is mostly dark before OCR runs.

Because the column split is a fixed estimate rather than a per-page
measurement, a row that doesn't look like a plausible asset name (too
short, mostly non-letters, or built from the kind of prose fragments that
leak in from the certification/Filer Notes text below the table on a
short table) is dropped rather than kept as a wrong or empty transaction —
an honest zero rows from a page beats a fabricated one. This makes scanned
recall genuinely partial and template-dependent: some real filings will
extract every transaction, some will extract a subset, and a heavily
degraded scan may extract none at all with the Filing row still valid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import numpy as np
import pypdfium2 as pdfium
import pytesseract
from PIL import Image
from pytesseract import Output

from capitol_lake.schema import (
    AssetType,
    Chamber,
    Filing,
    Owner,
    Provenance,
    Transaction,
)
from capitol_lake.stages import _house_form

EXTRACTOR_NAME = "house-scanned-pdf"

FULL_CONFIDENCE = 1.0
LOW_CONFIDENCE = 0.0

# Render resolution: enough to keep printed/handwritten digits legible
# without the runtime cost of a higher DPI (one filing per Lambda
# invocation, but still bounded by its 15-minute timeout).
_RENDER_DPI = 400

# Words from the form's own header, used to score which of the two
# candidate rotations (the paper form is always fed sideways) is upright.
_ORIENTATION_KEYWORDS = ("HOUSE", "REPRESENTATIVES", "TRANSACTION", "PERIODIC", "ASSET", "NAME")

# Fixed fractions of a (rotated, upright) page's width/height that isolate
# the asset-name column, the two date-of-transaction columns, and the
# table's body start, calibrated against sampled real scanned PTRs (#37).
# Coarser than the zonal OCR ADR 0002 declined: drifting a few percent
# changes only how much checkbox noise rides along, never which value a
# checkbox mark means.
_ASSET_COLUMN_RATIO = 0.30
_AMOUNT_COLUMN_RATIO = 0.69
_TABLE_TOP_RATIO = 0.55

# A row or column of pixels this dark is almost certainly a table border,
# not text; blanking it keeps grid lines from merging into digits.
_GRIDLINE_DARK_FRACTION = 0.6

_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_NAME_RE = re.compile(r"name\s*[:;.,]?\s*(?P<name>[A-Za-z][A-Za-z .,'\-]*)", re.IGNORECASE)
_NAME_STOP_RE = re.compile(r"\b(OFFICE|TELEPHONE|MEMBER|STATE|DISTRICT)\b", re.IGNORECASE)
# The Legislative Resource Center's date-received stamp, e.g.
# "2021 JUL 28 PH 5:39" ("PH" is OCR's usual misread of "PM"; a leading "2"
# also comes back as "4" often enough that the year is read as its last two
# digits and re-prefixed with "20" rather than matched literally).
_STAMP_RE = re.compile(
    r"(?P<year>\d{4})\D{0,4}"
    r"(?P<month>JAN|FEB|MAR|HAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\D{0,4}"
    r"(?P<day>\d{1,2})\D{0,8}P[MH]",
    re.IGNORECASE,
)
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "HAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

# A recovered "row" this short, this non-alphabetic, or built only from
# words that read as certification-section prose (leaking in below a short
# table) is dropped rather than kept as a wrong or empty transaction.
_MIN_ROW_LENGTH = 6
_MIN_ROW_ALPHA_FRACTION = 0.6
_BOILERPLATE_ROW_SNIPPETS = (
    "example",
    "ticker symbol",
    "provide full",
    "note number",
    "footnote",
    "filer note",
    "publicly disclosed",
)
_PROSE_STOPWORDS = {
    "was",
    "not",
    "aware",
    "that",
    "this",
    "which",
    "from",
    "have",
    "been",
    "the",
    "and",
    "for",
    "are",
    "month",
}


@dataclass(frozen=True)
class ScannedExtraction:
    """The silver rows extracted from one scanned House PTR."""

    filing: Filing
    transactions: list[Transaction]


def _doc_id_from_bronze_key(bronze_key: str) -> str:
    filename = bronze_key.rsplit("/", 1)[-1]
    return filename.split(".")[0]


def _rasterize(pdf_bytes: bytes) -> list[Image.Image]:
    pdf = pdfium.PdfDocument(pdf_bytes)
    return [page.render(scale=_RENDER_DPI / 72).to_pil() for page in pdf]


def _best_rotation_angle(first_page: Image.Image) -> int:
    """Pick whichever of the two sideways corrections reads as upright.

    The form's mediabox is always portrait but its content is landscape, so
    the only two candidates are +/-90 degrees; whichever OCRs more of the
    form's own header words is upright, and that same direction is reused
    for every page of the filing.
    """
    best_angle, best_score = 90, -1
    for angle in (90, 270):
        candidate = first_page.rotate(angle, expand=True)
        text = pytesseract.image_to_string(candidate, config="--psm 3").upper()
        score = sum(text.count(keyword) for keyword in _ORIENTATION_KEYWORDS)
        if score > best_score:
            best_score, best_angle = score, angle
    return best_angle


def _remove_gridlines(image: Image.Image) -> Image.Image:
    """Blank mostly-dark rows/columns of pixels so a border never merges into a digit."""
    arr = np.array(image.convert("L"))
    dark = arr < 128
    cleaned = arr.copy()
    for x in np.where(dark.mean(axis=0) > _GRIDLINE_DARK_FRACTION)[0]:
        cleaned[:, max(0, x - 2) : x + 3] = 255
    for y in np.where(dark.mean(axis=1) > _GRIDLINE_DARK_FRACTION)[0]:
        cleaned[max(0, y - 2) : y + 3, :] = 255
    return Image.fromarray(cleaned)


def _line_texts(data: dict, key_prefix: tuple = ()) -> list[tuple[int, str]]:
    """Group `image_to_data` words into lines, returning `(top, text)` sorted top to bottom."""
    lines: dict[tuple, dict] = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        line = lines.setdefault(key, {"words": [], "top": data["top"][i]})
        line["words"].append((data["left"][i], word))
        line["top"] = min(line["top"], data["top"][i])
    ordered = sorted(lines.values(), key=lambda line: line["top"])
    return [(line["top"], " ".join(w for _, w in sorted(line["words"]))) for line in ordered]


def _looks_like_asset_text(text: str) -> bool:
    if len(text) < _MIN_ROW_LENGTH:
        return False
    letters = sum(c.isalpha() for c in text)
    if letters / len(text) < _MIN_ROW_ALPHA_FRACTION:
        return False
    low = text.lower()
    if any(snippet in low for snippet in _BOILERPLATE_ROW_SNIPPETS):
        return False
    words = re.findall(r"[A-Za-z']+", low)
    return not any(word in _PROSE_STOPWORDS for word in words)


def _table_rows(image: Image.Image) -> list[dict]:
    """Best-effort per-row `(asset_text, dates)` pairs from a page's transaction table.

    Two crops, one OCR pass each: the asset-name column (`--psm 4`, a
    single column of stacked cells) and the two date-of-transaction columns
    (grid lines removed first, `--psm 6`). Rows are paired by vertical
    order between the two crops, not coordinate matching, since grid-line
    removal shifts pixels and the crops don't share a coordinate space. A
    row whose asset text doesn't look plausible (`_looks_like_asset_text`)
    is dropped rather than kept as a wrong or empty transaction.
    """
    width, height = image.size
    asset_boundary = int(width * _ASSET_COLUMN_RATIO)
    amount_boundary = int(width * _AMOUNT_COLUMN_RATIO)
    table_top = int(height * _TABLE_TOP_RATIO)

    asset_crop = image.crop((0, table_top, asset_boundary, height))
    asset_data = pytesseract.image_to_data(asset_crop, config="--psm 4", output_type=Output.DICT)
    asset_lines = _line_texts(asset_data)

    rows = [{"text": text} for _, text in asset_lines if _looks_like_asset_text(text)]
    if not rows:
        return []

    dates_crop = _remove_gridlines(image.crop((asset_boundary, table_top, amount_boundary, height)))
    dates_data = pytesseract.image_to_data(dates_crop, config="--psm 6", output_type=Output.DICT)
    date_texts = [text for _, text in _line_texts(dates_data)]

    # Rows are paired by relative order: the i-th surviving asset row lines
    # up with the i-th date-zone line. This drifts if a row's asset text
    # was dropped as implausible but its date-zone line wasn't (or vice
    # versa); when that happens the mispaired dates simply fail to match
    # `_DATE_RE` cleanly or land on the wrong row, which is why dates are
    # LOW_CONFIDENCE whenever they can't be parsed rather than trusted blindly.
    for i, row in enumerate(rows):
        text = date_texts[i] if i < len(date_texts) else ""
        row["dates"] = _DATE_RE.findall(text)
    return rows


def _parse_filer_name(text: str) -> str | None:
    match = _NAME_RE.search(text)
    if match is None:
        return None
    candidate = match.group("name")
    stop = _NAME_STOP_RE.search(candidate)
    if stop is not None:
        candidate = candidate[: stop.start()]
    candidate = candidate.strip(" .:;,")
    return candidate or None


def _parse_filing_date(text: str) -> date | None:
    match = _STAMP_RE.search(text)
    if match is None:
        return None
    month = _MONTHS.get(match.group("month").upper())
    if month is None:
        return None
    year = 2000 + int(match.group("year")) % 100
    try:
        return date(year, month, int(match.group("day")))
    except ValueError:
        return None


def _parse_date(raw: str) -> date | None:
    try:
        month, day, year = (int(part) for part in raw.split("/"))
        if year < 100:
            year += 2000
        return date(year, month, day)
    except ValueError:
        return None


def _parse_transaction(row: dict, filing: Filing, line_no: int) -> Transaction | None:
    text = row["text"]
    owner_match = _house_form.OWNER_RE.match(text)
    owner_raw = owner_match.group("owner") if owner_match else ""
    description = text[owner_match.end() :].strip() if owner_match else text
    if not description:
        return None

    code_match = _house_form.ASSET_TYPE_CODE_RE.search(description)
    if code_match is None:
        asset_type, asset_type_confidence = AssetType.OTHER, LOW_CONFIDENCE
        ticker = None
    else:
        asset_type = _house_form.ASSET_TYPES.get(code_match.group("code").upper(), AssetType.OTHER)
        asset_type_confidence = FULL_CONFIDENCE
        ticker = None
        if asset_type in (AssetType.STOCK, AssetType.ETF):
            symbol_match = _house_form.PRINTED_SYMBOL_RE.search(description)
            if symbol_match is not None:
                ticker = symbol_match.group(1).upper()

    dates = [d for raw in row["dates"] if (d := _parse_date(raw)) is not None]
    transaction_date = dates[0] if dates else None
    notification_date = dates[1] if len(dates) > 1 else None

    field_confidence = {
        "owner": LOW_CONFIDENCE if owner_match is None else FULL_CONFIDENCE,
        "asset_type": asset_type_confidence,
        "transaction_date": FULL_CONFIDENCE if transaction_date else LOW_CONFIDENCE,
        "notification_date": FULL_CONFIDENCE if notification_date else LOW_CONFIDENCE,
        # Checkbox grids (ADR 0002 and its #37 addendum): never resolved.
        "transaction_type": LOW_CONFIDENCE,
        "value_range": LOW_CONFIDENCE,
    }
    if transaction_date is None:
        # Transaction.transaction_date is required; a row OCR couldn't date
        # isn't a transaction we can honestly place in time.
        return None

    return Transaction(
        doc_id=filing.doc_id,
        line_no=line_no,
        owner=_house_form.OWNERS.get(owner_raw, Owner.SELF),
        owner_raw=owner_raw,
        transaction_type=None,
        transaction_type_raw="",
        asset_type=asset_type,
        asset_description=description,
        transaction_date=transaction_date,
        filing_date=filing.filing_date,
        value_range=None,
        confidence=min(field_confidence.values()),
        provenance=filing.provenance,
        ticker=ticker,
        notification_date=notification_date,
        field_confidence=field_confidence,
    )


def extract_scanned(pdf_bytes: bytes, *, bronze_key: str) -> ScannedExtraction:
    """Extract a scanned House PTR's `Filing` and `Transaction` rows.

    `pdf_bytes` is the bronze object at `bronze_key` (recorded as every
    row's provenance); `doc_id` comes from `bronze_key` itself, not OCR —
    the Filing ID footer digital filings carry as text has no scanned
    equivalent reliable enough to read. Raises `ValueError` when the filer
    name or the Legislative Resource Center's date-received stamp can't be
    read from any page: both are needed for every `Filing`, unlike a
    transaction row, which is simply dropped when it can't be read
    honestly (see the module docstring).
    """
    pages = _rasterize(pdf_bytes)
    rotation = _best_rotation_angle(pages[0])
    pages = [page.rotate(rotation, expand=True) for page in pages]
    page_texts = [pytesseract.image_to_string(page, config="--psm 3") for page in pages]
    full_text = "\n".join(page_texts)

    # Restricted to page 1: on a multi-column header, psm 3's block reading
    # order occasionally reorders a distant table-header word right after
    # "NAME", so searching the whole document risks matching, e.g., "AMOUNT
    # OF TRANSACTION" as the filer's name instead.
    filer_name = _parse_filer_name(page_texts[0])
    filing_date = _parse_filing_date(full_text)
    if filer_name is None or filing_date is None:
        raise ValueError(f"{bronze_key}: missing filer name or date-received stamp")

    filing = Filing(
        doc_id=_doc_id_from_bronze_key(bronze_key),
        chamber=Chamber.HOUSE,
        filer_name=filer_name,
        filing_date=filing_date,
        year=filing_date.year,
        confidence=FULL_CONFIDENCE,
        provenance=Provenance(bronze_key=bronze_key, extractor=EXTRACTOR_NAME),
    )

    transactions = []
    for page in pages:
        for row in _table_rows(page):
            transaction = _parse_transaction(row, filing, len(transactions) + 1)
            if transaction is not None:
                transactions.append(transaction)

    return ScannedExtraction(filing=filing, transactions=transactions)
