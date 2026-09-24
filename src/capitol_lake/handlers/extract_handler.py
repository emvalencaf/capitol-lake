"""Thin Lambda adapter for the extract stage.

Wires a Lambda event's `bronze_key` to `extract_house_filing`, fetching the
bronze PDF and writing the two returned silver Parquet part files with a
real S3 client (`boto3`). It also wires `resolve_ticker`'s OpenFIGI +
EDGAR cascade to real HTTP (stdlib `urllib`, same as the collector
handlers): OpenFIGI's `/v3/search` is queried per unresolved stock/ETF row,
and EDGAR's `company_tickers.json` listing is fetched once per invocation
(module-level `_EDGAR_COMPANIES`, reused across every row) rather than
queried per row, since it's a static full listing, not a search endpoint.
Handlers stay thin by convention: they only translate the event shape and
real clients into the pure function's arguments and are not unit-tested
(see docs/local-dev.md); the pure functions underneath are.
"""

import json
import os
from urllib.request import Request, urlopen

import boto3

from capitol_lake.schema import AssetType
from capitol_lake.stages.extract import extract_house_filing
from capitol_lake.stages.ticker_resolve import (
    EdgarCompany,
    parse_edgar_company_tickers,
    parse_openfigi_search_response,
)
from capitol_lake.stages.ticker_resolve import resolve_ticker as _resolve_ticker_cascade

USER_AGENT = "capitol-lake ticker resolver (contact: edsonmvf@gmail.com)"
BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")
SILVER_BUCKET = os.environ.get("SILVER_BUCKET", "silver")

OPENFIGI_SEARCH_URL = "https://api.openfigi.com/v3/search"
EDGAR_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_EDGAR_COMPANIES: list[EdgarCompany] | None = None


def _fetch_json(url: str, *, data: bytes | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    with urlopen(request) as response:
        return json.loads(response.read())


def _search_openfigi(query: str) -> list:
    api_key = os.environ.get("OPENFIGI_API_KEY")
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
    request = Request(
        OPENFIGI_SEARCH_URL, data=json.dumps({"query": query}).encode("utf-8"), headers=headers
    )
    with urlopen(request) as response:
        return parse_openfigi_search_response(json.loads(response.read()))


def _edgar_companies() -> list[EdgarCompany]:
    global _EDGAR_COMPANIES
    if _EDGAR_COMPANIES is None:
        _EDGAR_COMPANIES = parse_edgar_company_tickers(_fetch_json(EDGAR_COMPANY_TICKERS_URL))
    return _EDGAR_COMPANIES


def _resolve_ticker(asset_description: str, asset_type: AssetType) -> str | None:
    return _resolve_ticker_cascade(
        asset_description,
        asset_type,
        search_openfigi=_search_openfigi,
        edgar_companies=_edgar_companies(),
    )


def handler(event: dict, context: object) -> dict:
    s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))

    bronze_key = event["bronze_key"]
    pdf_bytes = s3_client.get_object(Bucket=BRONZE_BUCKET, Key=bronze_key)["Body"].read()

    result = extract_house_filing(pdf_bytes, bronze_key=bronze_key, resolve_ticker=_resolve_ticker)

    for table in ("filings", "transactions"):
        part = result[table]
        s3_client.put_object(Bucket=SILVER_BUCKET, Key=part["key"], Body=part["bytes"])

    return {
        "kind": result["kind"],
        "filings_key": result["filings"]["key"],
        "transactions_key": result["transactions"]["key"],
    }
