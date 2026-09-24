"""Ticker resolution cascade (#39): OpenFIGI + EDGAR, no live calls.

`search_openfigi` and `edgar_companies` are always canned/injected here, per
the acceptance criteria: the decision logic is exercised against fixed
responses, never a real network call.
"""

from capitol_lake.schema import AssetType
from capitol_lake.stages.ticker_resolve import (
    EdgarCompany,
    OpenFigiCandidate,
    clean_asset_name,
    parse_edgar_company_tickers,
    parse_openfigi_search_response,
    resolve_ticker,
)


def _openfigi(*candidates: OpenFigiCandidate):
    def _search(query: str) -> list[OpenFigiCandidate]:
        _search.calls.append(query)
        return list(candidates)

    _search.calls = []
    return _search


def test_gated_to_stock_and_etf_asset_types():
    search = _openfigi(OpenFigiCandidate(ticker="AMGN", name="AMGEN INC"))

    for asset_type in AssetType:
        if asset_type in (AssetType.STOCK, AssetType.ETF):
            continue
        assert resolve_ticker("Amgen Inc.", asset_type, search_openfigi=search) is None

    # Never even calls OpenFIGI for a non-stock/ETF asset type.
    assert search.calls == []


def test_accepts_exact_top1_match_from_openfigi():
    search = _openfigi(
        OpenFigiCandidate(ticker="AMGN", name="AMGEN INC"),
        OpenFigiCandidate(ticker="XYZ", name="SOME UNRELATED CO"),
    )

    ticker = resolve_ticker(
        "Amgen Inc. - Common Stock (AMGN) [ST]", AssetType.STOCK, search_openfigi=search
    )

    assert ticker == "AMGN"
    # Queried with the asset-type-code/parenthetical suffix stripped.
    assert search.calls == ["Amgen Inc. - Common Stock"]


def test_accepts_near_exact_top1_match_from_openfigi():
    search = _openfigi(OpenFigiCandidate(ticker="ROL", name="ROLLINS INC"))

    ticker = resolve_ticker(
        "Rollins, Inc. Common Stock [ST]", AssetType.STOCK, search_openfigi=search
    )

    assert ticker == "ROL"


def test_rejects_top1_match_that_is_not_near_exact_even_when_ranked_first():
    # OpenFIGI's free-text search can rank a same-shaped but different
    # company first; that must never be accepted outright.
    search = _openfigi(OpenFigiCandidate(ticker="XYZ", name="TOTALLY DIFFERENT HOLDINGS CORP"))

    ticker = resolve_ticker("Amgen Inc. [ST]", AssetType.STOCK, search_openfigi=search)

    assert ticker is None


def test_escalates_to_edgar_to_confirm_a_lower_confidence_openfigi_candidate():
    search = _openfigi(
        OpenFigiCandidate(ticker="XYZ", name="TOTALLY DIFFERENT HOLDINGS CORP"),
        OpenFigiCandidate(ticker="AMGN", name="AMGEN INC"),
    )
    edgar_companies = [EdgarCompany(ticker="AMGN", title="Amgen Inc.")]

    ticker = resolve_ticker(
        "Amgen Inc. [ST]",
        AssetType.STOCK,
        search_openfigi=search,
        edgar_companies=edgar_companies,
    )

    assert ticker == "AMGN"


def test_edgar_never_introduces_a_ticker_openfigi_did_not_propose():
    # EDGAR only confirms a candidate OpenFIGI already returned; it must
    # never be used to invent a ticker of its own.
    search = _openfigi(OpenFigiCandidate(ticker="XYZ", name="TOTALLY DIFFERENT HOLDINGS CORP"))
    edgar_companies = [EdgarCompany(ticker="AMGN", title="Amgen Inc.")]

    ticker = resolve_ticker(
        "Amgen Inc. [ST]",
        AssetType.STOCK,
        search_openfigi=search,
        edgar_companies=edgar_companies,
    )

    assert ticker is None


def test_no_confident_match_at_any_stage_yields_null_ticker():
    search = _openfigi(OpenFigiCandidate(ticker="XYZ", name="TOTALLY DIFFERENT HOLDINGS CORP"))
    edgar_companies = [EdgarCompany(ticker="ABC", title="Also Unrelated Ltd")]

    ticker = resolve_ticker(
        "Amgen Inc. [ST]",
        AssetType.STOCK,
        search_openfigi=search,
        edgar_companies=edgar_companies,
    )

    assert ticker is None


def test_no_confident_match_when_openfigi_returns_no_candidates():
    search = _openfigi()

    ticker = resolve_ticker("Amgen Inc. [ST]", AssetType.STOCK, search_openfigi=search)

    assert ticker is None


def test_clean_asset_name_strips_asset_type_code_and_trailing_parenthetical():
    assert clean_asset_name("Amgen Inc. - Common Stock (AMGN) [ST]") == "Amgen Inc. - Common Stock"
    assert clean_asset_name("Some Fund (Class A) [EF]") == "Some Fund"
    assert clean_asset_name("US TREASURY BILL DUE 03/20/25 (912797KJ5) [GS]") == (
        "US TREASURY BILL DUE 03/20/25"
    )


def test_parse_openfigi_search_response_skips_error_and_empty_responses():
    assert parse_openfigi_search_response({"error": "No identifier found."}) == []
    assert parse_openfigi_search_response({"data": []}) == []
    assert parse_openfigi_search_response({}) == []


def test_parse_openfigi_search_response_reads_ticker_and_name():
    response = {
        "data": [
            {"figi": "BBG000BBQCY0", "ticker": "AMGN", "name": "AMGEN INC", "exchCode": "US"},
            {"figi": "BBG000BBQCY1", "ticker": "AMGN", "name": "AMGEN INC", "exchCode": "GB"},
        ]
    }

    candidates = parse_openfigi_search_response(response)

    assert candidates == [
        OpenFigiCandidate(ticker="AMGN", name="AMGEN INC"),
        OpenFigiCandidate(ticker="AMGN", name="AMGEN INC"),
    ]


def test_parse_edgar_company_tickers_reads_ticker_and_title():
    response = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 318154, "ticker": "AMGN", "title": "Amgen Inc."},
    }

    companies = parse_edgar_company_tickers(response)

    assert companies == [
        EdgarCompany(ticker="AAPL", title="Apple Inc."),
        EdgarCompany(ticker="AMGN", title="Amgen Inc."),
    ]
