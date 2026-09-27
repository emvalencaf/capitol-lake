"""Per-run quality gate: fail-without-overwrite checks over run summaries (#42).

A `RunSummary` is an aggregate snapshot of one silver-write run for one
table (`filings` or `transactions`) — not the rows themselves. It is cheap
to persist alongside a run's other operational metadata and compare across
runs without re-reading any Parquet. `evaluate_quality_gate` combines the
three independent checks the spec's story 38 / issue #22 decided on:

  (a) `check_volume_regression` — the current run's `row_count` dropped more
      than `regression_threshold` (default 50%) from the prior run's.
  (b) `check_completeness` — any field a caller's `RunSummary.null_counts`
      names (a design-intentionally-non-null one, per `schema.py`'s
      `Filing`/`Transaction` docstrings — a field typed without `| None`,
      as opposed to one like `Transaction.ticker` that is honestly
      nullable) came back null on at least one row this run.
  (c) `check_row_count_divergence` — the current run's `row_count` disagrees
      with the source-index-announced count (the collector's own listing of
      how many filings/rows should exist), when that count is known.

Each check is a pure function over `RunSummary` value objects, independent
of the orchestration layer that would compute or persist them (#43, out of
scope here) — exactly the seam the spec's testing decisions call for.
`evaluate_quality_gate` never touches S3 or any prior-run store itself; a
caller supplies both summaries and, on a failing `GateResult`, is
responsible for skipping the silver overwrite.

Distinct from the gold-set evaluation metric (`evaluation.py`, #40): that
metric measures extraction *accuracy* against hand labels, while this gate
only reasons about run-to-run operational health (volume, completeness,
row-count sanity) and knows nothing about ground truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_REGRESSION_THRESHOLD = 0.5


@dataclass(frozen=True)
class RunSummary:
    """One run's operational-health snapshot for a single silver table.

    `null_counts` maps a design-intentionally-non-null field name (per
    `schema.py`'s `Filing`/`Transaction` — a field typed without `| None`)
    to how many of this run's `row_count` rows had it null; a field that's
    honestly nullable (e.g. `Transaction.ticker`) is never a key here.
    `announced_count` is the source-index-announced row count for this run
    (`None` when not known), never the prior run's.
    """

    row_count: int
    null_counts: Mapping[str, int]
    announced_count: int | None = None


@dataclass(frozen=True)
class GateFailure:
    """One reason `evaluate_quality_gate` failed the run."""

    reason: str
    detail: str


@dataclass(frozen=True)
class GateResult:
    """The gate's verdict: pass, or the failures that blocked it."""

    passed: bool
    failures: tuple[GateFailure, ...]


def check_volume_regression(
    prior: RunSummary,
    current: RunSummary,
    *,
    threshold: float = DEFAULT_REGRESSION_THRESHOLD,
) -> GateFailure | None:
    """Fail when `current.row_count` dropped more than `threshold` from `prior`'s.

    A prior run with `row_count == 0` has nothing to regress from (and
    would divide by zero), so it never fails this check — the completeness
    and row-count-divergence checks still apply to `current` on their own.
    """
    if prior.row_count <= 0:
        return None
    drop = (prior.row_count - current.row_count) / prior.row_count
    if drop > threshold:
        return GateFailure(
            reason="volume_regression",
            detail=(
                f"row_count dropped {drop:.0%} from the prior run "
                f"({prior.row_count} -> {current.row_count}), exceeding the "
                f"{threshold:.0%} threshold"
            ),
        )
    return None


def check_completeness(current: RunSummary) -> GateFailure | None:
    """Fail when any design-intentionally-non-null field had a null this run."""
    offending = {field: count for field, count in current.null_counts.items() if count > 0}
    if offending:
        return GateFailure(
            reason="completeness",
            detail=f"non-null fields had nulls this run: {offending}",
        )
    return None


def check_row_count_divergence(current: RunSummary) -> GateFailure | None:
    """Fail when `current.row_count` disagrees with the source-index-announced count.

    Never fails when `announced_count` is `None` (not known for this run).
    """
    if current.announced_count is None:
        return None
    if current.row_count != current.announced_count:
        return GateFailure(
            reason="row_count_divergence",
            detail=(
                f"row_count {current.row_count} diverges from the "
                f"source-index-announced count {current.announced_count}"
            ),
        )
    return None


def evaluate_quality_gate(
    prior: RunSummary,
    current: RunSummary,
    *,
    regression_threshold: float = DEFAULT_REGRESSION_THRESHOLD,
) -> GateResult:
    """Run all three checks and return one verdict.

    `passed` is `True` only when none of the three checks failed; a caller
    skips the silver overwrite on a failing result and proceeds on a
    passing one. This never touches S3 or any prior-run store — both
    summaries are supplied by the caller.
    """
    failures = tuple(
        failure
        for failure in (
            check_volume_regression(prior, current, threshold=regression_threshold),
            check_completeness(current),
            check_row_count_divergence(current),
        )
        if failure is not None
    )
    return GateResult(passed=not failures, failures=failures)
