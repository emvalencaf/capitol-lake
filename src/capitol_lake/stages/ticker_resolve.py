"""Ticker resolution stage: OpenFIGI + EDGAR cascade (#39).

An extractor already fills `Transaction.ticker` from the House form's own
printed symbol when one is present (`_house_form.PRINTED_SYMBOL_RE`); this
module only resolves the remaining stock/ETF lines that printed no symbol,
by asset name. It never overwrites a ticker the extractor already found.

The cascade is deliberately cautious: OpenFIGI's free-text search
(`search_openfigi`, injected so this stays network-free and testable
against canned responses) is tried first, and its top-1 result is accepted
only when its name is an exact or near-exact match for the asset
description — a same-shaped but different company must never be accepted
just because it ranked first. When the top result isn't confident enough,
EDGAR (`edgar_companies`, the full SEC `company_tickers.json` listing,
fetched once by the caller rather than queried per line) is consulted only
to *confirm* one of OpenFIGI's own candidate tickers by an independent
near-exact name match — EDGAR is never allowed to introduce a ticker
OpenFIGI didn't already propose. Any stage of the cascade that fails to
produce a confident match yields `None`, never a best-effort guess.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from capitol_lake.schema import AssetType

TICKER_ASSET_TYPES = frozenset({AssetType.STOCK, AssetType.ETF})

_NEAR_EXACT_RATIO = 0.9

_ASSET_TYPE_CODE_RE = re.compile(r"\[[A-Za-z0-9]{2}\]\s*$")
_TRAILING_PAREN_RE = re.compile(r"\([^()]*\)\s*$")

_CORP_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|"
    r"common stock|ordinary shares|class [a-z]|the)\b"
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class OpenFigiCandidate:
    """One match from an OpenFIGI `/v3/search` response."""

    ticker: str
    name: str


@dataclass(frozen=True)
class EdgarCompany:
    """One entry from SEC's `company_tickers.json` listing."""

    ticker: str
    title: str


def clean_asset_name(asset_description: str) -> str:
    """Strip the House form's asset-type-code/ticker-or-CUSIP suffix for a search query.

    `asset_description` keeps that suffix verbatim (e.g. `"Amgen Inc. -
    Common Stock (AMGN) [ST]"`, or `"Some Fund (Class A) [EF]"` when no
    ticker printed); neither the trailing `[XX]` code nor whatever sits in
    the parenthesis right before it is useful free text for a name search.
    """
    text = _ASSET_TYPE_CODE_RE.sub("", asset_description).strip()
    text = _TRAILING_PAREN_RE.sub("", text).strip()
    return text.strip(" -")


def _normalize(name: str) -> str:
    stripped = _CORP_SUFFIX_RE.sub(" ", name.lower())
    return _NON_ALNUM_RE.sub(" ", stripped).strip()


def _is_near_exact_match(query: str, candidate_name: str) -> bool:
    normalized_query = _normalize(query)
    normalized_candidate = _normalize(candidate_name)
    if not normalized_query or not normalized_candidate:
        return False
    if normalized_query == normalized_candidate:
        return True
    ratio = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
    return ratio >= _NEAR_EXACT_RATIO


def parse_openfigi_search_response(response: Mapping[str, Any]) -> list[OpenFigiCandidate]:
    """Parse a raw OpenFIGI `/v3/search` JSON body into ranked candidates.

    An error response (`{"error": ...}`) or one with an empty/missing
    `data` list yields no candidates rather than raising: an OpenFIGI
    outage or a query with no results both mean the cascade has nothing to
    accept, exactly like any other no-confident-match case.
    """
    data = response.get("data") or []
    candidates = []
    for entry in data:
        ticker = entry.get("ticker")
        name = entry.get("name")
        if ticker and name:
            candidates.append(OpenFigiCandidate(ticker=ticker, name=name))
    return candidates


def parse_edgar_company_tickers(response: Mapping[str, Mapping[str, Any]]) -> list[EdgarCompany]:
    """Parse SEC's `company_tickers.json` payload (`{"0": {...}, "1": {...}, ...}`)."""
    companies = []
    for entry in response.values():
        ticker = entry.get("ticker")
        title = entry.get("title")
        if ticker and title:
            companies.append(EdgarCompany(ticker=str(ticker), title=str(title)))
    return companies


def resolve_ticker(
    asset_description: str,
    asset_type: AssetType,
    *,
    search_openfigi: Callable[[str], Sequence[OpenFigiCandidate]],
    edgar_companies: Sequence[EdgarCompany] = (),
) -> str | None:
    """Resolve a stock/ETF asset name to a ticker via the OpenFIGI + EDGAR cascade.

    Gated to `TICKER_ASSET_TYPES` (stock/ETF): every other `asset_type`
    returns `None` immediately, without calling `search_openfigi` at all,
    since resolution is never attempted for them (#39). The query sent to
    `search_openfigi` is `asset_description` with the form's own
    asset-type-code/ticker-or-CUSIP suffix stripped (`clean_asset_name`).

    OpenFIGI's top-1 candidate is accepted outright when its name is an
    exact or near-exact match for the cleaned name. Otherwise EDGAR's
    listing is checked for a near-exact name match whose ticker also
    appears among OpenFIGI's own candidates — confirming, never
    substituting, an OpenFIGI-proposed ticker. No confident match at either
    stage returns `None`.
    """
    if asset_type not in TICKER_ASSET_TYPES:
        return None

    query = clean_asset_name(asset_description)
    figi_candidates = list(search_openfigi(query))
    if not figi_candidates:
        return None

    top = figi_candidates[0]
    if _is_near_exact_match(query, top.name):
        return top.ticker

    figi_tickers = {candidate.ticker for candidate in figi_candidates}
    for company in edgar_companies:
        if company.ticker in figi_tickers and _is_near_exact_match(query, company.title):
            return company.ticker

    return None
