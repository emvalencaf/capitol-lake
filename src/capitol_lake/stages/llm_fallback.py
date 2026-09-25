"""LLM fallback stage (#41): per-field structured-output recovery for weak `Transaction` fields.

The rule-based extractors (`digital_extract`, `scanned_extract`) leave a
field null, or flag it `LOW_CONFIDENCE`, when the source can't be read
honestly rather than guess a value (ADR 0002, ADR 0003). This stage is an
*optional* second pass over exactly those fields, gated two ways so it is
never invoked unconditionally on every null:

1. **Per field group**: `eligible_fields_from_scores` only admits a field
   whose macro-averaged score from `evaluation.score_gold_set` (the
   evaluation harness, #40, i.e. the spec's "ticket 10") is below a caller-
   supplied threshold. A field the rule-based cascade already handles well
   is never sent to an LLM at all.
2. **Per transaction**: `fields_needing_fallback` further narrows to fields
   that are actually null or `LOW_CONFIDENCE` on *this* transaction, even
   within an eligible field group.

The structured-output contract (`fallback_schema`) is built directly from
the silver schema's own field names and types (`evaluation.SCORED_FIELDS`,
`schema.Owner`/`TransactionType`/`AssetType`) — there is no separate DTO or
translation layer between what the LLM returns and what `Transaction`
stores; `apply_fallback_result` only coerces JSON scalars (strings, numbers)
to the native Python types the schema already uses (enums, `date`, `float`).

Two entry points mirror ADR 0002's digital-vs-scanned split: a digital
filing's still-null fields go through `apply_text_fallback` (the PDF's own
text, which a rule-based extractor already parses); a scanned filing's go
through `apply_vision_fallback`, directly on the scanned page image, since
OCR text is the same lossy signal that produced the null in the first place.
Both are provider-agnostic: `complete_text`/`complete_vision` are injected
callables (see `capitol_lake.llm_providers` for concrete LM Studio/Gemini/Groq
implementations), following this codebase's convention of never calling a
network dependency directly from a stage (`ticker_resolve.resolve_ticker`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from capitol_lake.evaluation import SCORED_FIELDS
from capitol_lake.schema import AssetType, Owner, Transaction, TransactionType, ValueRange

# Appended to `Provenance.extractor` when a fallback pass touches a
# transaction, so a silver row's own provenance says an LLM was involved,
# never silently blending it in with a purely rule-based reading.
FALLBACK_SUFFIX = "llm-fallback"

# Confidence assigned to a field the fallback stage fills: above
# LOW_CONFIDENCE (a second pass looked at it) but below the rule-based
# extractors' FULL_CONFIDENCE (1.0) — an LLM completion is not the same
# guarantee as a validated label or anchor match.
LLM_CONFIDENCE = 0.5

# Every SCORED_FIELDS name is a valid fallback target: the eval harness and
# this stage share the exact same field vocabulary by construction.
FALLBACK_FIELDS = SCORED_FIELDS

_ENUM_FIELDS: dict[str, type] = {
    "owner": Owner,
    "transaction_type": TransactionType,
    "asset_type": AssetType,
}
_DATE_FIELDS = frozenset({"transaction_date", "notification_date"})
_NUMBER_FIELDS = frozenset({"value_min", "value_max"})

_ACCESSORS: dict[str, Callable[[Transaction], Any]] = {
    "owner": lambda t: t.owner.value if t.owner is not None else None,
    "transaction_type": lambda t: t.transaction_type.value if t.transaction_type else None,
    "asset_type": lambda t: t.asset_type.value if t.asset_type is not None else None,
    "transaction_date": lambda t: t.transaction_date,
    "value_min": lambda t: t.value_range.min if t.value_range else None,
    "value_max": lambda t: t.value_range.max if t.value_range else None,
    "notification_date": lambda t: t.notification_date,
    "asset_description": lambda t: t.asset_description,
    "filing_status": lambda t: t.filing_status,
    "sub_owner": lambda t: t.sub_owner,
    "description": lambda t: t.description,
}


def field_schema(field: str) -> dict[str, Any]:
    """One `SCORED_FIELDS` field's JSON-Schema type, mirroring the silver schema directly."""
    if field in _ENUM_FIELDS:
        return {
            "type": ["string", "null"],
            "enum": [member.value for member in _ENUM_FIELDS[field]],
        }
    if field in _DATE_FIELDS:
        return {"type": ["string", "null"], "format": "date"}
    if field in _NUMBER_FIELDS:
        return {"type": ["number", "null"]}
    return {"type": ["string", "null"]}


def fallback_schema(fields: Iterable[str]) -> dict[str, Any]:
    """A JSON Schema `object` covering exactly `fields`: this stage's structured-output contract."""
    fields = list(fields)
    return {
        "type": "object",
        "properties": {field: field_schema(field) for field in fields},
        "required": fields,
        "additionalProperties": False,
    }


def eligible_fields_from_scores(scores: Mapping[str, float], threshold: float) -> frozenset[str]:
    """Fields whose evaluation score is below `threshold` (the spec's "ticket 10" gate).

    `scores` is one `{field: score}` mapping from `evaluation.score_gold_set`
    (e.g. `report["by_kind"]["digital"]` or `["scanned"]`), as printed by
    `scripts/run_eval.py --json`. A field not present in `scores` is treated
    as already adequate (not eligible), never as automatically weak.
    """
    return frozenset(field for field in FALLBACK_FIELDS if scores.get(field, 1.0) < threshold)


def needs_fallback(transaction: Transaction, field: str) -> bool:
    """True when `field` is null on `transaction`, or the extractor flagged it `LOW_CONFIDENCE`."""
    if _ACCESSORS[field](transaction) is None:
        return True
    return transaction.field_confidence.get(field, 1.0) < 1.0


def fields_needing_fallback(transaction: Transaction, eligible_fields: Iterable[str]) -> list[str]:
    """The subset of `eligible_fields` that is actually null/low-confidence on `transaction`.

    This is the per-transaction half of the stage's two-level gate: even a
    field group evaluation flagged as weak is only ever sent to an LLM for a
    transaction where it's genuinely missing or unreliable, never for one
    the rule-based cascade already read confidently.
    """
    return [
        field
        for field in eligible_fields
        if field in _ACCESSORS and needs_fallback(transaction, field)
    ]


def _coerce_value(field: str, raw: Any) -> Any:
    if raw is None:
        return None
    if field in _ENUM_FIELDS:
        return _ENUM_FIELDS[field](raw)
    if field in _DATE_FIELDS:
        return raw if isinstance(raw, date) else date.fromisoformat(raw)
    if field in _NUMBER_FIELDS:
        return float(raw)
    return str(raw)


def _filing_date(transaction: Transaction) -> date:
    """Recover the `filing_date` `Transaction.__post_init__` consumed to compute `disclosure_lag`.

    `filing_date` is an `InitVar`, never stored on the frozen dataclass, so
    `dataclasses.replace` can't recover it on its own; it's reconstructed
    from the two fields that *are* stored (same trick `test_extract.py`
    uses at the call site).
    """
    return transaction.transaction_date + timedelta(days=transaction.disclosure_lag)


def apply_fallback_result(
    transaction: Transaction, fields: Sequence[str], result: Mapping[str, Any]
) -> Transaction:
    """Return a new `Transaction` with `fields` filled from `result`, a raw structured-output dict.

    Only `fields` are touched; every other attribute is copied unchanged.
    `value_min`/`value_max` are combined into a single `ValueRange` (or
    `None`, if the filled `value_min` is itself null) since the schema
    stores them as one field. Each filled field's `field_confidence` becomes
    `LLM_CONFIDENCE`, `confidence` is lowered to match if it was higher, and
    `provenance.extractor` gains a `FALLBACK_SUFFIX` marker — a fallback-
    touched row is never indistinguishable from a purely rule-based one.
    """
    fields = list(fields)
    if not fields:
        return transaction
    updates: dict[str, Any] = {}
    field_confidence = dict(transaction.field_confidence)
    value_min = transaction.value_range.min if transaction.value_range else None
    value_max = transaction.value_range.max if transaction.value_range else None
    value_range_touched = False

    for field in fields:
        value = _coerce_value(field, result.get(field))
        if field == "value_min":
            value_min, value_range_touched = value, True
        elif field == "value_max":
            value_max, value_range_touched = value, True
        else:
            updates[field] = value
        field_confidence[field] = LLM_CONFIDENCE

    if value_range_touched:
        updates["value_range"] = ValueRange(value_min, value_max) if value_min is not None else None

    updates["field_confidence"] = field_confidence
    updates["confidence"] = min(transaction.confidence, *(field_confidence[f] for f in fields))
    updates["provenance"] = replace(
        transaction.provenance, extractor=f"{transaction.provenance.extractor}+{FALLBACK_SUFFIX}"
    )
    return replace(transaction, filing_date=_filing_date(transaction), **updates)


def _prompt(transaction: Transaction, fields: Sequence[str]) -> str:
    known = {
        field: _ACCESSORS[field](transaction)
        for field in FALLBACK_FIELDS
        if field not in fields and _ACCESSORS[field](transaction) is not None
    }
    return (
        "Fill in the missing fields of one line item of a congressional "
        "stock-trading disclosure (Periodic Transaction Report). Return "
        "only the requested fields as JSON matching the given schema; set a "
        "field null if it truly cannot be determined, never guess.\n"
        f"Known fields on this line: {known!r}\n"
        f"Fields to fill: {list(fields)!r}"
    )


def apply_text_fallback(
    transaction: Transaction,
    eligible_fields: Iterable[str],
    *,
    source_text: str,
    complete_text: Callable[[str, str, dict[str, Any]], Mapping[str, Any]],
) -> Transaction:
    """Recover a digital filing's null/low-confidence fields via text structured output.

    `complete_text(prompt, source_text, schema)` is the injected provider
    call (see `capitol_lake.llm_providers`); `schema` is `fallback_schema`'s
    output for exactly the fields this transaction still needs. Returns
    `transaction` unchanged, without calling `complete_text` at all, when
    nothing needs recovering (`fields_needing_fallback` is empty) — the
    stage never invokes a provider for a transaction it has nothing to ask
    about.
    """
    fields = fields_needing_fallback(transaction, eligible_fields)
    if not fields:
        return transaction
    result = complete_text(_prompt(transaction, fields), source_text, fallback_schema(fields))
    return apply_fallback_result(transaction, fields, result)


def apply_vision_fallback(
    transaction: Transaction,
    eligible_fields: Iterable[str],
    *,
    page_image: bytes,
    complete_vision: Callable[[str, bytes, dict[str, Any]], Mapping[str, Any]],
) -> Transaction:
    """Recover a scanned filing's null/low-confidence fields via vision structured output.

    Same contract as `apply_text_fallback`, except `complete_vision(prompt,
    page_image, schema)` reads the scanned page image directly rather than
    an OCR transcript: `transaction_type` and `value_range` are checkbox
    grids full-page OCR destroys (ADR 0002 and its #37 addendum), so a text
    prompt built from that same OCR output would be recovering from the
    signal that produced the null in the first place.
    """
    fields = fields_needing_fallback(transaction, eligible_fields)
    if not fields:
        return transaction
    result = complete_vision(_prompt(transaction, fields), page_image, fallback_schema(fields))
    return apply_fallback_result(transaction, fields, result)
