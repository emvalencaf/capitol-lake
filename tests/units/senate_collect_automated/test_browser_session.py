import json
from datetime import date
from pathlib import Path

import pytest

from senate_collect_automated.browser_session import (
    LOOKBACK_DAYS,
    classify_search_response,
    filings_to_fetch,
    search_date_window,
)
from shared.senate_index import SenateIndexEntry

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# classify_search_response (the PTR search form's own DataTables JSON)
# ---------------------------------------------------------------------------


def test_cleared_on_real_recorded_search_response():
    body = (FIXTURES / "senate_search_sample.json").read_text()
    assert classify_search_response(200, body) == "cleared"


def test_cleared_on_search_response_with_empty_data_list():
    assert classify_search_response(200, json.dumps({"data": []})) == "cleared"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "   ",
        "<html><body><h1>Access Denied</h1><p>Reference #18.abc123.def</p></body></html>",
    ],
)
def test_search_response_blocked_akamai_on_403_with_akamai_shape(body):
    assert classify_search_response(403, body) == "blocked_akamai"


def test_search_response_blocked_other_on_403_without_akamai_markers():
    assert classify_search_response(403, "<html><body>Forbidden</body></html>") == "blocked_other"


@pytest.mark.parametrize("status_code", [500, 503, 404, 302])
def test_search_response_blocked_other_on_non_200_non_403_status(status_code):
    assert classify_search_response(status_code, "{}") == "blocked_other"


def test_search_response_ambiguous_on_200_non_json_body():
    assert classify_search_response(200, "<html><title>eFD: Home</title></html>") == "ambiguous"


def test_search_response_ambiguous_on_200_json_without_data_list():
    assert classify_search_response(200, json.dumps({"draw": 1})) == "ambiguous"


# ---------------------------------------------------------------------------
# search_date_window
# ---------------------------------------------------------------------------


def test_search_date_window_spans_lookback_days_ending_today():
    from_date, to_date = search_date_window(date(2026, 9, 25))

    assert to_date == "09/25/2026"
    assert from_date == "09/18/2026"


def test_search_date_window_uses_mm_dd_yyyy_format():
    from_date, to_date = search_date_window(date(2026, 1, 3))

    assert from_date == "12/27/2025"
    assert to_date == "01/03/2026"


def test_lookback_days_is_seven():
    assert LOOKBACK_DAYS == 7


# ---------------------------------------------------------------------------
# filings_to_fetch (the 300-filings-per-run cap, #67)
# ---------------------------------------------------------------------------


def _entries(n):
    return [
        SenateIndexEntry(filing_id=f"filing-{i}", year=2026, kind="ptr", index_row=i)
        for i in range(n)
    ]


def test_filings_to_fetch_passes_through_when_under_the_cap():
    entries = _entries(3)

    assert filings_to_fetch(entries, max_filings=300) == entries


def test_filings_to_fetch_caps_overflow_leaving_the_rest_for_next_run():
    entries = _entries(5)

    assert filings_to_fetch(entries, max_filings=3) == entries[:3]


def test_filings_to_fetch_preserves_order():
    entries = _entries(10)

    capped = filings_to_fetch(entries, max_filings=4)

    assert [e.filing_id for e in capped] == [
        "filing-0",
        "filing-1",
        "filing-2",
        "filing-3",
    ]
