from capitol_lake.browser.senate_efd_session import classify_probe_result as _canonical
from capitol_lake.probes.senate_akamai_probe import classify_probe_result

# ---------------------------------------------------------------------------
# classify_probe_result is re-exported unchanged from
# capitol_lake.browser.senate_efd_session (#67) — see
# tests/test_senate_efd_session.py for the full classification behavior.
# ---------------------------------------------------------------------------


def test_classify_probe_result_is_the_canonical_function():
    assert classify_probe_result is _canonical
