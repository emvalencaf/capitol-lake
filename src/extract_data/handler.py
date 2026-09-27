"""Thin Lambda adapter for the extract stage.

Wires a Lambda event to `extract_house_filing` for every bronze key the
event carries, fetching each bronze PDF and writing the two returned silver
Parquet part files with a real S3 client (`boto3`). It also wires
`resolve_ticker`'s OpenFIGI + EDGAR cascade to real HTTP (stdlib `urllib`,
same as the collector handlers): OpenFIGI's `/v3/search` is queried per
unresolved stock/ETF row, and EDGAR's `company_tickers.json` listing is
fetched once per invocation (module-level `_EDGAR_COMPANIES`, reused across
every row) rather than queried per row, since it's a static full listing,
not a search endpoint. Handlers stay thin by convention: they only
translate the event shape and real clients into the pure function's
arguments and are not unit-tested (see docs/local-dev.md); the pure
functions underneath are.

Per the orchestration shape settled in #18/#43 and refined by ADR-0015, this
Lambda is chained from `house_collect/handler` via SQS (one message per
bronze key, batch size 1) and, for the Senate side (no scheduled
collector), via that same SQS queue fed by an S3 event notification on the
bronze bucket rather than a direct invoke; `shared.orchestration`'s
`bronze_keys_from_event` dispatches on both message shapes plus the plain
`{"bronze_key": ...}` invocation this handler always accepted (kept for
manual/RIE testing, see docs/local-dev.md). Filings are still processed
one at a time and each one's failure is independent (`_process_one` isn't
allowed to let one filing's exception affect another's): given an SQS
event, a per-record failure is reported back as an item in
`batchItemFailures` so only that message is retried/DLQ'd, not the whole
batch (see #43's DLQ posture — this handler also carries the ticker/LLM-
fallback and silver-write steps, per this module's docstring history, so
its queue's DLQ is the "ticker/LLM-fallback" one #43 asks for slower
backoff, not more retries, on); a plain/S3-event invocation instead lets a
failure raise, matching every other handler's existing behavior.

The LLM fallback stage (#41) is wired the same way, conditionally:
`_build_llm_fallback` only returns a callable when `LLM_FALLBACK_ENABLED` is
set, an eval report is available at `LLM_FALLBACK_EVAL_REPORT` (the JSON
`scripts/run_eval.py --json` produces), and that report's `by_kind[kind]`
scores actually leave at least one field below `LLM_FALLBACK_THRESHOLD`
(`llm_fallback.eligible_fields_from_scores`) — never unconditionally on
every null, per the issue's acceptance criteria. Only the digital path
(text structured output over the PDF's own text layer) is wired here: a
scanned filing's vision fallback needs the specific page image a
transaction's row came from, which `scanned_extract.ScannedExtraction`
doesn't yet track per transaction, so `apply_vision_fallback` (fully
implemented and tested in `extract_data/llm_fallback.py`) is left for a follow-up
once that tracking exists, rather than guessing which page to send.
"""

import io
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

import boto3
from pypdf import PdfReader

from extract_data.extract import extract_house_filing
from extract_data.llm_fallback import apply_text_fallback, eligible_fields_from_scores
from extract_data.ticker_resolve import (
    EdgarCompany,
    parse_edgar_company_tickers,
    parse_openfigi_search_response,
)
from extract_data.ticker_resolve import resolve_ticker as _resolve_ticker_cascade
from shared.doc_id import route_doc_id
from shared.llm_providers import provider_from_env
from shared.orchestration import bronze_key_records_from_event
from shared.schema import AssetType, Transaction
from shared.wide_event import log_progress, wide_event

USER_AGENT = "capitol-lake ticker resolver (contact: edsonmvf@gmail.com)"
BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "bronze")
SILVER_BUCKET = os.environ.get("SILVER_BUCKET", "silver")

OPENFIGI_SEARCH_URL = "https://api.openfigi.com/v3/search"
EDGAR_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_DEFAULT_LLM_FALLBACK_THRESHOLD = 0.8

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


def _digital_source_text(pdf_bytes: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages)


def _build_llm_fallback(kind: str, pdf_bytes: bytes):
    """A digital-filing `llm_fallback` callable for `extract_house_filing`, or `None`.

    `None` (no fallback at all) whenever any gate isn't satisfied: the
    feature flag is off, no eval report is configured/found, or that
    report's `by_kind[kind]` scores leave nothing below the threshold. See
    module docstring for why `kind == "scanned"` always yields `None` here.
    """
    if os.environ.get("LLM_FALLBACK_ENABLED", "").lower() not in ("1", "true"):
        return None
    if kind != "digital":
        return None

    report_path = os.environ.get("LLM_FALLBACK_EVAL_REPORT")
    if not report_path or not Path(report_path).is_file():
        return None
    report = json.loads(Path(report_path).read_text())
    scores = report.get("by_kind", {}).get(kind, {})
    threshold = float(os.environ.get("LLM_FALLBACK_THRESHOLD", _DEFAULT_LLM_FALLBACK_THRESHOLD))
    eligible_fields = eligible_fields_from_scores(scores, threshold)
    if not eligible_fields:
        return None

    provider = provider_from_env()
    source_text = _digital_source_text(pdf_bytes)

    def _llm_fallback(transaction: Transaction) -> Transaction:
        return apply_text_fallback(
            transaction,
            eligible_fields,
            source_text=source_text,
            complete_text=provider.complete_text,
        )

    return _llm_fallback


def _process_one(s3_client, bronze_key: str) -> dict:
    pdf_bytes = s3_client.get_object(Bucket=BRONZE_BUCKET, Key=bronze_key)["Body"].read()

    kind = route_doc_id(Path(bronze_key).stem)
    llm_fallback = _build_llm_fallback(kind, pdf_bytes)
    result = extract_house_filing(
        pdf_bytes,
        bronze_key=bronze_key,
        resolve_ticker=_resolve_ticker,
        llm_fallback=llm_fallback,
    )

    for table in ("filings", "transactions"):
        part = result[table]
        s3_client.put_object(Bucket=SILVER_BUCKET, Key=part["key"], Body=part["bytes"])

    return {
        "kind": result["kind"],
        "filings_key": result["filings"]["key"],
        "transactions_key": result["transactions"]["key"],
        # Whether `_build_llm_fallback`'s gates (feature flag, digital kind,
        # eval report present, eligible fields below threshold) let the LLM
        # fallback run at all for this filing — not whether it actually
        # changed any row, which `extract_house_filing` doesn't report.
        "llm_fallback_used": llm_fallback is not None,
    }


def handler(event: dict, context: object) -> dict:
    with wide_event("extract", context) as log:
        s3_client = boto3.client("s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3"))
        records = bronze_key_records_from_event(event)
        log["record_count"] = len(records)

        if "bronze_key" in event:
            log["mode"] = "direct"
            result = _process_one(s3_client, records[0].bronze_key)
            log["kind"] = result["kind"]
            log["llm_fallback_used"] = result["llm_fallback_used"]
            return result

        total = len(records)

        if not any(record.message_id is not None for record in records):
            log["mode"] = "batch_no_sqs"
            results = []
            for index, record in enumerate(records, start=1):
                result = _process_one(s3_client, record.bronze_key)
                results.append(result)
                log_progress(
                    "extract",
                    context,
                    index=index,
                    total=total,
                    bronze_key=record.bronze_key,
                    kind=result["kind"],
                    llm_fallback_used=result["llm_fallback_used"],
                )
            log["processed_count"] = len(results)
            return {"results": results}

        log["mode"] = "sqs_batch"
        batch_item_failures = []
        for index, record in enumerate(records, start=1):
            try:
                result = _process_one(s3_client, record.bronze_key)
                log_progress(
                    "extract",
                    context,
                    index=index,
                    total=total,
                    bronze_key=record.bronze_key,
                    kind=result["kind"],
                    llm_fallback_used=result["llm_fallback_used"],
                    outcome="processed",
                )
            except Exception as exc:
                log_progress(
                    "extract",
                    context,
                    index=index,
                    total=total,
                    bronze_key=record.bronze_key,
                    outcome="failed",
                    error={"type": type(exc).__name__, "message": str(exc)},
                )
                if record.message_id is not None:
                    batch_item_failures.append({"itemIdentifier": record.message_id})
        log["failed_count"] = len(batch_item_failures)
        log["processed_count"] = len(records) - len(batch_item_failures)
        return {"batchItemFailures": batch_item_failures}
