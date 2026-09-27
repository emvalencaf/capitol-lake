"""Per-run quality gate (#42): three independent checks over canned run summaries.

No orchestration layer involved — every check and `evaluate_quality_gate`
itself are exercised directly against `RunSummary` value objects.
"""

from extract_data.quality_gate import (
    GateResult,
    RunSummary,
    check_completeness,
    check_row_count_divergence,
    check_volume_regression,
    evaluate_quality_gate,
)


def _summary(row_count=100, null_counts=None, announced_count=None):
    return RunSummary(
        row_count=row_count,
        null_counts=null_counts or {},
        announced_count=announced_count,
    )


# -- check_volume_regression --------------------------------------------------


def test_regression_passes_when_current_matches_prior():
    prior = _summary(row_count=100)
    current = _summary(row_count=100)
    assert check_volume_regression(prior, current) is None


def test_regression_passes_when_current_grew():
    prior = _summary(row_count=100)
    current = _summary(row_count=150)
    assert check_volume_regression(prior, current) is None


def test_regression_passes_at_exactly_the_threshold():
    prior = _summary(row_count=100)
    current = _summary(row_count=50)  # exactly a 50% drop
    assert check_volume_regression(prior, current) is None


def test_regression_fails_past_the_threshold():
    prior = _summary(row_count=100)
    current = _summary(row_count=49)  # 51% drop
    failure = check_volume_regression(prior, current)
    assert failure is not None
    assert failure.reason == "volume_regression"
    assert "100" in failure.detail and "49" in failure.detail


def test_regression_respects_custom_threshold():
    prior = _summary(row_count=100)
    current = _summary(row_count=90)  # a 10% drop
    assert check_volume_regression(prior, current, threshold=0.05) is not None
    assert check_volume_regression(prior, current, threshold=0.5) is None


def test_regression_never_fails_when_prior_run_was_empty():
    prior = _summary(row_count=0)
    current = _summary(row_count=0)
    assert check_volume_regression(prior, current) is None


# -- check_completeness --------------------------------------------------


def test_completeness_passes_with_no_nulls():
    current = _summary(null_counts={"doc_id": 0, "filer_name": 0})
    assert check_completeness(current) is None


def test_completeness_fails_on_any_null_in_a_required_field():
    current = _summary(null_counts={"doc_id": 0, "filer_name": 2})
    failure = check_completeness(current)
    assert failure is not None
    assert failure.reason == "completeness"
    assert "filer_name" in failure.detail


def test_completeness_reports_every_offending_field():
    current = _summary(null_counts={"doc_id": 1, "asset_type": 3, "owner": 0})
    failure = check_completeness(current)
    assert "doc_id" in failure.detail
    assert "asset_type" in failure.detail
    assert "owner" not in failure.detail


# -- check_row_count_divergence --------------------------------------------------


def test_row_count_divergence_passes_when_counts_match():
    current = _summary(row_count=42, announced_count=42)
    assert check_row_count_divergence(current) is None


def test_row_count_divergence_passes_when_announced_count_is_unknown():
    current = _summary(row_count=42, announced_count=None)
    assert check_row_count_divergence(current) is None


def test_row_count_divergence_fails_on_mismatch():
    current = _summary(row_count=40, announced_count=42)
    failure = check_row_count_divergence(current)
    assert failure is not None
    assert failure.reason == "row_count_divergence"
    assert "40" in failure.detail and "42" in failure.detail


# -- evaluate_quality_gate --------------------------------------------------


def test_gate_passes_a_healthy_run():
    prior = _summary(row_count=100)
    current = _summary(row_count=100, null_counts={"doc_id": 0}, announced_count=100)
    result = evaluate_quality_gate(prior, current)
    assert result == GateResult(passed=True, failures=())


def test_gate_fails_and_reports_every_failing_check():
    prior = _summary(row_count=100)
    current = _summary(
        row_count=10,  # 90% drop -> volume regression
        null_counts={"doc_id": 3},  # completeness
        announced_count=20,  # row_count (10) diverges from this
    )
    result = evaluate_quality_gate(prior, current)
    assert result.passed is False
    reasons = {failure.reason for failure in result.failures}
    assert reasons == {"volume_regression", "completeness", "row_count_divergence"}


def test_gate_regression_threshold_is_configurable():
    prior = _summary(row_count=100)
    current = _summary(row_count=90)
    assert evaluate_quality_gate(prior, current, regression_threshold=0.5).passed is True
    assert evaluate_quality_gate(prior, current, regression_threshold=0.05).passed is False
