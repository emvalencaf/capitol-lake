"""Full-document LLM extractor (#89): benchmark-only alternative to the rule-based extractors.

Distinct from `extract_data.llm_fallback`: the fallback stage patches
individual null/low-confidence fields *after* a rule-based extractor runs;
`extract_llm` never runs after a rule-based extractor and reads a filing's
transactions from scratch, purely so it can be scored side by side with
`extract_digital`/`extract_scanned` in `scripts/run_house_eval.py`. It is not
wired into `extract_house_filing` and produces no production silver data.

Matches the same `(pdf_bytes, *, bronze_key) -> {filing, transactions}` shape
as the other two extractors, and is provider-agnostic like `llm_fallback`
(a `shared.llm_providers.Provider` is injected, never imported directly).
One provider call is made per page rather than per filing: pages are
processed independently and their returned transactions concatenated in
page order, then renumbered — the same document-order convention
`extract_digital`/`extract_scanned` use for `line_no`.

Digital filings always use `provider.complete_text` on the PDF's own text
(there's no ambiguity to resolve, unlike scanned filings). Scanned filings
support both `provider.complete_text` on OCR'd page text and
`provider.complete_vision` on the rendered page image directly
(`input_mode`), reusing `scanned_extract`'s page rasterization/rotation so
both this module and the rule-based scanned extractor agree on what
"upright" means for a given filing.

The structured-output schema for one transaction reuses
`llm_fallback.field_schema` directly (ADR 0019): the same field vocabulary
and enums the fallback stage already asks an LLM for, now requested for
every `SCORED_FIELDS` field instead of just the missing ones.

`Filing` metadata (filer name, filing date) is never asked of the model:
`evaluation.SCORED_FIELDS`/`score_gold_set` only score `Transaction` fields,
so a placeholder `Filing` (doc id and year from the bronze key; a filer name
that says so) is exactly as usable for benchmarking as an accurate one, at
the cost of one LLM call per page instead of two.

A transaction the model can't honestly place in time (`transaction_date`
null) or can't name (`asset_description` null/empty) is dropped rather than
constructed with a fabricated value, mirroring `scanned_extract`'s "an
honest zero rows beats a fabricated one" convention (ADR 0002). A
malformed field (an enum value the model invented) drops that transaction
the same way, rather than failing the whole filing over one bad row.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import pypdf
import pytesseract

from extract_data import scanned_extract
from extract_data.evaluation import SCORED_FIELDS
from extract_data.llm_fallback import fallback_schema
from shared.doc_id import route_doc_id
from shared.keys import parse_bronze_key
from shared.llm_providers import Provider
from shared.schema import (
    AssetType,
    Chamber,
    Filing,
    Owner,
    Provenance,
    Transaction,
    TransactionType,
    ValueRange,
)

EXTRACTOR_NAME = "house-llm"

# Below the rule-based extractors' FULL_CONFIDENCE (1.0): an LLM completion
# is not the same guarantee as a validated label or anchor match, matching
# `llm_fallback.LLM_CONFIDENCE`.
LLM_CONFIDENCE = 0.5

InputMode = Literal["text", "vision"]

_PROMPT = (
    "You are extracting line items from one page of a congressional Periodic "
    "Transaction Report (PTR), a disclosure of a securities transaction. "
    "Return every transaction line item on this page, top to bottom, as JSON "
    'matching the given schema: a list under "transactions". If this page has '
    "no transaction line items, return an empty list. Set a field null if it "
    "cannot be determined from this page; never guess a value."
)


@dataclass(frozen=True)
class LlmExtraction:
    """The silver rows a full LLM extraction pass produced for one filing."""

    filing: Filing
    transactions: list[Transaction]


def transaction_schema() -> dict[str, Any]:
    """One transaction's JSON-Schema object, covering every `SCORED_FIELDS` field.

    Delegates to `llm_fallback.fallback_schema` (built the same way, from
    `SCORED_FIELDS` + the silver enums) so the two stages' structured-output
    contracts can never drift apart from each other (ADR 0019's
    comparability requirement).
    """
    return fallback_schema(SCORED_FIELDS)


def page_schema() -> dict[str, Any]:
    """This module's structured-output contract: a list of transactions for one page."""
    return {
        "type": "object",
        "properties": {"transactions": {"type": "array", "items": transaction_schema()}},
        "required": ["transactions"],
        "additionalProperties": False,
    }


def _page_texts(pdf_bytes: bytes) -> list[str]:
    return [page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages]


def _upright_pages(pdf_bytes: bytes) -> list:
    """A scanned filing's pages, rasterized and rotated upright (reuses `scanned_extract`)."""
    pages = scanned_extract._rasterize(pdf_bytes)
    rotation = scanned_extract._best_rotation_angle(pages[0])
    return [page.rotate(rotation, expand=True) for page in pages]


def _ocr_texts(pdf_bytes: bytes) -> list[str]:
    return [
        pytesseract.image_to_string(page, config="--psm 3") for page in _upright_pages(pdf_bytes)
    ]


def _page_images(pdf_bytes: bytes) -> list[bytes]:
    images = []
    for page in _upright_pages(pdf_bytes):
        buffer = io.BytesIO()
        page.save(buffer, format="PNG")
        images.append(buffer.getvalue())
    return images


def _coerce(field: str, raw: Any) -> Any:
    if raw is None:
        return None
    if field == "owner":
        return Owner(raw)
    if field == "transaction_type":
        return TransactionType(raw)
    if field == "asset_type":
        return AssetType(raw)
    if field in ("transaction_date", "notification_date"):
        return raw if isinstance(raw, date) else date.fromisoformat(raw)
    if field in ("value_min", "value_max"):
        return float(raw)
    return str(raw)


def build_transaction(raw: Mapping[str, Any], filing: Filing, line_no: int) -> Transaction | None:
    """One `Transaction` from a page response's raw transaction dict, or `None` to drop it.

    Dropped rather than raised when a required `Transaction` field can't be
    honestly filled (`transaction_date`, `asset_description`) or the model
    returned a value outside a field's enum (`ValueError`) — see the module
    docstring's "honest zero rows" rationale. A dropped row costs that one
    line in the eval score, not the whole filing.
    """
    try:
        values = {field: _coerce(field, raw.get(field)) for field in SCORED_FIELDS}
    except ValueError:
        return None
    if values["transaction_date"] is None or not values["asset_description"]:
        return None

    owner = values["owner"] or Owner.SELF
    asset_type = values["asset_type"] or AssetType.OTHER
    transaction_type = values["transaction_type"]
    value_min, value_max = values["value_min"], values["value_max"]
    value_range = ValueRange(value_min, value_max) if value_min is not None else None
    return Transaction(
        doc_id=filing.doc_id,
        line_no=line_no,
        owner=owner,
        owner_raw=owner.value,
        transaction_type=transaction_type,
        transaction_type_raw=transaction_type.value if transaction_type else "",
        asset_type=asset_type,
        asset_description=values["asset_description"],
        transaction_date=values["transaction_date"],
        filing_date=filing.filing_date,
        value_range=value_range,
        confidence=LLM_CONFIDENCE,
        provenance=filing.provenance,
        notification_date=values["notification_date"],
        filing_status=values["filing_status"],
        sub_owner=values["sub_owner"],
        description=values["description"],
        field_confidence=dict.fromkeys(SCORED_FIELDS, LLM_CONFIDENCE),
    )


def extract_llm(
    pdf_bytes: bytes,
    *,
    bronze_key: str,
    provider: Provider,
    input_mode: InputMode = "text",
) -> LlmExtraction:
    """Extract a House PTR's transactions via `provider`, one call per page.

    `bronze_key` supplies `doc_id`/`year` (`parse_bronze_key`) and, via
    `route_doc_id`, whether the filing is digital or scanned: a digital
    filing always uses `provider.complete_text` on the PDF's own text; a
    scanned filing uses `input_mode` to choose between OCR text
    (`complete_text`) and the rendered page image (`complete_vision`).
    Raises whatever `provider`'s call raises (a rate limit, a timeout, a
    provider with no vision model) uncaught — a real provider failure is
    itself part of what a benchmark run of this extractor measures (ADR
    0019), not something to paper over here.
    """
    _, year, doc_id = parse_bronze_key(bronze_key)
    kind = route_doc_id(doc_id)
    filing = Filing(
        doc_id=doc_id,
        chamber=Chamber.HOUSE,
        # Filing metadata is never scored (evaluation.SCORED_FIELDS covers
        # only Transaction fields); a real filer name/date would cost a
        # second provider call per filing for no benchmark value.
        filer_name="(unscored placeholder: house-llm extraction)",
        filing_date=date(year, 1, 1),
        year=year,
        confidence=LLM_CONFIDENCE,
        provenance=Provenance(bronze_key=bronze_key, extractor=EXTRACTOR_NAME),
    )

    if kind == "digital":
        pages, complete = _page_texts(pdf_bytes), provider.complete_text
    elif input_mode == "vision":
        pages, complete = _page_images(pdf_bytes), provider.complete_vision
    else:
        pages, complete = _ocr_texts(pdf_bytes), provider.complete_text

    schema = page_schema()
    raw_transactions: list[Mapping[str, Any]] = []
    for page in pages:
        result = complete(_PROMPT, page, schema)
        raw_transactions.extend(result.get("transactions", []))

    transactions: list[Transaction] = []
    for raw in raw_transactions:
        transaction = build_transaction(raw, filing, len(transactions) + 1)
        if transaction is not None:
            transactions.append(transaction)

    return LlmExtraction(filing=filing, transactions=transactions)
