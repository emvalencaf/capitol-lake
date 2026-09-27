from senate_akamai_probe.probe import classify_probe_result
from shared.senate_efd_classification import classify_probe_result as _canonical

# ---------------------------------------------------------------------------
# classify_probe_result is re-exported unchanged from
# shared.senate_efd_classification (#67) — see
# tests/units/shared/test_senate_efd_classification.py for the full
# classification behavior.
# ---------------------------------------------------------------------------


def test_classify_probe_result_is_the_canonical_function():
    assert classify_probe_result is _canonical
