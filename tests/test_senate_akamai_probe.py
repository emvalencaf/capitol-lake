from pathlib import Path

import pytest

from capitol_lake.probes.senate_akamai_probe import classify_probe_result

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# classify_probe_result
# ---------------------------------------------------------------------------


def test_cleared_on_real_ptr_page():
    html = (FIXTURES / "senate_ptr_sample.html").read_text()
    assert classify_probe_result(200, html) == "cleared"


@pytest.mark.parametrize(
    "html",
    [
        "",
        "   ",
        "<html><body><h1>Access Denied</h1><p>Reference #18.abc123.def</p></body></html>",
        "<html><body>Reference #99.deadbeef.0</body></html>",
    ],
)
def test_blocked_akamai_on_403_with_akamai_shape(html):
    assert classify_probe_result(403, html) == "blocked_akamai"


def test_blocked_other_on_403_without_akamai_markers():
    html = "<html><body><h1>Forbidden</h1></body></html>"
    assert classify_probe_result(403, html) == "blocked_other"


@pytest.mark.parametrize("status_code", [500, 503, 404, 302])
def test_blocked_other_on_non_200_non_403_status(status_code):
    assert classify_probe_result(status_code, "<html></html>") == "blocked_other"


def test_ambiguous_on_200_without_cleared_marker():
    html = "<html><head><title>Please Sign In</title></head><body></body></html>"
    assert classify_probe_result(200, html) == "ambiguous"
