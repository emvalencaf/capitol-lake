"""Per-field evaluation metrics for extracted `Transaction` rows against a hand-labelled gold set.

Follows issue #40 / #8's design: score every scored field of every
transaction, macro-average those scores first within a filing (one mean per
field, across that filing's transactions), then across filings within a set
(digital vs. scanned). Ticker and filing-level metadata fields are excluded
from the metric (a separate ticker-resolution cascade, #39, and near-100%
deterministic filing-level parsing already cover them) — only `Transaction`
fields are scored, matched between gold and prediction by `line_no`.

`EXACT_FIELDS` score 1.0/0.0 (both null counts as a match); `SIMILARITY_FIELDS`
score a continuous `difflib.SequenceMatcher` ratio in `[0, 1]` so a
near-miss free-text field (a truncated asset description, a reworded
`description` line) isn't scored identically to a completely wrong one. A
gold transaction with no matching predicted `line_no` scores 0.0 on every
field: a missed row is a total miss, not a partial one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from difflib import SequenceMatcher
from statistics import mean
from typing import Any

# Enums, dates and numbers: an extractor either read them right or didn't.
EXACT_FIELDS = (
    "owner",
    "transaction_type",
    "asset_type",
    "transaction_date",
    "value_min",
    "value_max",
    "notification_date",
)
# Free text: scored by similarity, not identity, so a near-miss still counts
# for something.
SIMILARITY_FIELDS = (
    "asset_description",
    "filing_status",
    "sub_owner",
    "description",
)
SCORED_FIELDS = EXACT_FIELDS + SIMILARITY_FIELDS


def _similarity(gold: str, predicted: str) -> float:
    return SequenceMatcher(a=gold, b=predicted).ratio()


def score_field(field: str, gold_value: Any, predicted_value: Any) -> float:
    """Score one field of one transaction, in `[0.0, 1.0]`.

    Both null is a match (1.0): a field the form has no line for is
    correctly reported null. Only one null is a total miss (0.0), never a
    partial similarity score against an empty string.
    """
    if gold_value is None or predicted_value is None:
        return 1.0 if gold_value is None and predicted_value is None else 0.0
    if field in SIMILARITY_FIELDS:
        return _similarity(str(gold_value), str(predicted_value))
    return 1.0 if gold_value == predicted_value else 0.0


def score_transaction(
    gold: Mapping[str, Any], predicted: Mapping[str, Any] | None
) -> dict[str, float]:
    """Score every `SCORED_FIELDS` field of one gold transaction.

    `predicted` is `None` when no predicted row shares this transaction's
    `line_no`: every field scores 0.0, since a missing row can't have
    gotten any field right.
    """
    if predicted is None:
        return dict.fromkeys(SCORED_FIELDS, 0.0)
    return {
        field: score_field(field, gold.get(field), predicted.get(field)) for field in SCORED_FIELDS
    }


def score_filing(
    gold_transactions: Sequence[Mapping[str, Any]],
    predicted_transactions: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """Per-field mean score across the union of a filing's gold and predicted line numbers.

    A gold row with no matching predicted `line_no` scores 0.0 on every
    field (a missed row). A *predicted* row with no matching gold `line_no`
    also scores 0.0 on every field: a hallucinated row is exactly the
    failure mode ADR 0002 calls out ("an honest zero rows... beats a
    fabricated one"), and must be penalized the same as a missed one,
    including on a filing with zero gold transactions (a legitimate "nothing
    to report" PTR) where an extractor that fabricates rows must not score
    perfectly just because there was nothing to miss.

    A filing with neither gold nor predicted transactions scores every
    field 1.0: there was nothing to get wrong, and nothing was fabricated.
    """
    gold_by_line = {row.get("line_no"): row for row in gold_transactions}
    predicted_by_line = {row.get("line_no"): row for row in predicted_transactions}
    line_nos = set(gold_by_line) | set(predicted_by_line)
    if not line_nos:
        return dict.fromkeys(SCORED_FIELDS, 1.0)

    per_transaction = [
        dict.fromkeys(SCORED_FIELDS, 0.0)
        if line_no not in gold_by_line
        else score_transaction(gold_by_line[line_no], predicted_by_line.get(line_no))
        for line_no in line_nos
    ]
    return {field: mean(scores[field] for scores in per_transaction) for field in SCORED_FIELDS}


def score_set(filing_scores: Sequence[Mapping[str, float]]) -> dict[str, float]:
    """Per-field mean score across a set's filing-level scores (macro by set)."""
    if not filing_scores:
        return dict.fromkeys(SCORED_FIELDS, 1.0)
    return {field: mean(scores[field] for scores in filing_scores) for field in SCORED_FIELDS}


def score_gold_set(filings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Score a whole gold set, broken out by digital vs. scanned, plus an overall row.

    Each item of `filings` is `{"doc_id": ..., "kind": "digital"|"scanned",
    "gold_transactions": [...], "predicted_transactions": [...]}`. Returns
    `{"by_filing": {doc_id: {field: score}}, "by_kind": {"digital": {...},
    "scanned": {...}}, "overall": {...}}`, each `{field: score}` mapping
    covering `SCORED_FIELDS`, macro-averaged by filing then by set/overall.
    """
    by_filing: dict[str, dict[str, float]] = {}
    scores_by_kind: dict[str, list[dict[str, float]]] = {"digital": [], "scanned": []}

    for item in filings:
        filing_score = score_filing(item["gold_transactions"], item["predicted_transactions"])
        by_filing[item["doc_id"]] = filing_score
        scores_by_kind[item["kind"]].append(filing_score)

    by_kind = {kind: score_set(scores) for kind, scores in scores_by_kind.items()}
    overall = score_set([score for scores in scores_by_kind.values() for score in scores])

    return {"by_filing": by_filing, "by_kind": by_kind, "overall": overall}


def weakest_fields(scores: Mapping[str, float], *, n: int = 3) -> list[tuple[str, float]]:
    """The `n` lowest-scoring fields of a `{field: score}` mapping, weakest first."""
    return sorted(scores.items(), key=lambda item: item[1])[:n]


def transaction_row_for_eval(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a silver transaction row (dict or `Transaction`-shaped mapping) for scoring.

    Gold rows are hand-written JSON, where a date can only be a string; a
    predicted row (`stages.extract.transaction_row`) carries real `date`
    objects. Both sides are normalized to the same ISO-string shape here so
    `score_field`'s exact-match comparison isn't comparing a `date` to a
    `str` and failing every date field by construction.
    """
    normalized = dict(row)
    for field in ("transaction_date", "notification_date"):
        value = normalized.get(field)
        if isinstance(value, date):
            normalized[field] = value.isoformat()
    return normalized
