import json
from pathlib import Path

import pytest

from shared.senate_index import (
    PAPER_FILING_KIND,
    PTR_FILING_KIND,
    RateLimiter,
    UnknownFilingKindError,
    parse_senate_index,
    route_filing_kind,
    senate_filing_url,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# route_filing_kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("ptr", PTR_FILING_KIND),
        ("PTR", PTR_FILING_KIND),
        (" ptr ", PTR_FILING_KIND),
        ("paper", PAPER_FILING_KIND),
        ("PAPER", PAPER_FILING_KIND),
    ],
)
def test_route_filing_kind_classifies_known_kinds(raw, kind):
    assert route_filing_kind(raw) == kind


@pytest.mark.parametrize("raw", ["annual", "extension-notice/regular"])
def test_route_filing_kind_raises_on_non_ptr_report_kinds(raw):
    with pytest.raises(UnknownFilingKindError):
        route_filing_kind(raw)


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------


def test_senate_filing_url_includes_filing_id_and_ptr_path():
    url = senate_filing_url("3b1f6a2e-1111-2222-3333-444455556666")
    assert "/ptr/" in url
    assert url.endswith("3b1f6a2e-1111-2222-3333-444455556666/")


# ---------------------------------------------------------------------------
# parse_senate_index
#
# `senate_search_sample.json` is a trimmed, real eFD `/search/report/data/`
# response (captured 2026-09-23), not synthetic data: each row is
# `[first, last, office, html_link, filed_date]`, `html_link` is an anchor
# like `<a href="/search/view/ptr/{uuid}/">...</a>`, and real search results
# mix report kinds (ptr, paper, annual, extension-notice/regular) and years
# in one response.
# ---------------------------------------------------------------------------


def _load_sample():
    return json.loads((FIXTURES / "senate_search_sample.json").read_text())


def test_parse_senate_index_keeps_only_ptr_rows_from_a_real_recorded_response():
    entries = parse_senate_index(_load_sample())

    assert [(e.filing_id, e.year, e.kind) for e in entries] == [
        ("b999bc0e-3eb0-4ca9-ab07-8e8f2e04b41f", 2026, "ptr"),
        ("fda235b3-bad7-4637-8fa1-053f354d929c", 2026, "ptr"),
    ]


def test_parse_senate_index_preserves_row_position_as_index_row():
    entries = parse_senate_index(_load_sample())

    # The two ptr rows sit at positions 5 and 6 in the fixture's data array.
    assert [e.index_row for e in entries] == [5, 6]


def test_parse_senate_index_skips_paper_rows():
    response = {
        "data": [
            [
                "Jane",
                "Doe",
                "Senator",
                '<a href="/search/view/paper/2701724B-A03B-4738-8E28-15D9FBBADEFE/">Annual</a>',
                "05/15/2012",
            ],
        ]
    }

    assert parse_senate_index(response) == []


def test_parse_senate_index_skips_rows_without_a_recognized_link():
    response = {
        "data": [
            ["Jane", "Doe", "Senator", "no link here", "05/15/2012"],
            ["", "", "", "", ""],
        ]
    }

    assert parse_senate_index(response) == []


def test_parse_senate_index_treats_amendment_as_a_separate_entry():
    response = {
        "data": [
            [
                "Jane",
                "Doe",
                "Senator",
                '<a href="/search/view/ptr/11111111-1111-1111-1111-111111111111/">PTR</a>',
                "01/02/2024",
            ],
            [
                "Jane",
                "Doe",
                "Senator",
                '<a href="/search/view/ptr/22222222-2222-2222-2222-222222222222/">PTR Amend</a>',
                "01/03/2024",
            ],
        ]
    }

    entries = parse_senate_index(response)

    assert [e.filing_id for e in entries] == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]


# ---------------------------------------------------------------------------
# RateLimiter (shared shape with the House collector; behavior re-verified here
# since senate_index owns its own instance)
# ---------------------------------------------------------------------------


def test_rate_limiter_does_not_sleep_on_first_call():
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: 100.0, sleep=sleeps.append)

    limiter.wait()

    assert sleeps == []


def test_rate_limiter_sleeps_remaining_interval_on_fast_second_call():
    clock_values = iter([100.0, 100.2, 100.2])
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: next(clock_values), sleep=sleeps.append)

    limiter.wait()
    limiter.wait()

    assert sleeps == [pytest.approx(0.8)]
