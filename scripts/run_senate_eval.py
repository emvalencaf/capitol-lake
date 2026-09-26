#!/usr/bin/env -S uv run --project .
"""Run the extraction evaluator against the hand-labelled Senate gold set.

Reads every `eval/senate_gold/*.json` file, routes its matching HTML from
`eval/senate_fixtures/<doc_id>.html` through `extract_senate_filing`, scores
the result against the gold transactions (`capitol_lake.evaluation`), and
prints a per-field report macro-averaged by filing then by set. Unlike
`run_eval.py`'s House set, there is no digital/scanned split to break out by
(Senate has one extractor for one source format), so this reports one
overall column. Also runs the one-time determinism check: each filing is
extracted twice and the two runs must produce byte-identical rows.

Usage: `uv run scripts/run_senate_eval.py [--json]`
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from capitol_lake.evaluation import SCORED_FIELDS, score_filing, score_set, transaction_row_for_eval
from capitol_lake.stages.extract import transaction_row
from capitol_lake.stages.senate_extract import extract_senate_html

ROOT = Path(__file__).parent.parent
GOLD_DIR = ROOT / "eval" / "senate_gold"
FIXTURES_DIR = ROOT / "eval" / "senate_fixtures"


def _extract(doc_id: str, year: int) -> list[dict]:
    html_bytes = (FIXTURES_DIR / f"{doc_id}.html").read_bytes()
    bronze_key = f"bronze/senate/year={year}/{doc_id}.html"
    extraction = extract_senate_html(html_bytes, bronze_key=bronze_key, doc_id=doc_id)
    return [transaction_row_for_eval(transaction_row(t)) for t in extraction.transactions]


def _extract_safe(doc_id: str, year: int) -> tuple[list[dict], str | None]:
    """`_extract`, but a bug on one filing must not abort the whole report.

    A raised exception is treated as a total extraction failure: no
    predicted rows at all, which `score_filing` already scores as a miss on
    every gold field. Surfaced in the report rather than silently swallowed.
    """
    try:
        return _extract(doc_id, year), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def load_gold_set() -> list[dict]:
    """Load every gold file plus its extraction outcome, once each."""
    filings = []
    for path in sorted(GOLD_DIR.glob("*.json")):
        gold = json.loads(path.read_text())
        predicted, error = _extract_safe(gold["doc_id"], gold["year"])
        filings.append(
            {
                "doc_id": gold["doc_id"],
                "year": gold["year"],
                "gold_transactions": [transaction_row_for_eval(t) for t in gold["transactions"]],
                "predicted_transactions": predicted,
                "extraction_error": error,
            }
        )
    return filings


def check_determinism(filing: dict) -> bool | None:
    """Two extraction runs of the same bytes must produce identical rows.

    Returns `None` (not applicable) when the filing didn't extract at all
    on the first pass.
    """
    if filing["extraction_error"] is not None:
        return None
    second, error = _extract_safe(filing["doc_id"], filing["year"])
    return error is None and filing["predicted_transactions"] == second


def score_gold_set(filings: list[dict]) -> dict:
    by_filing = {
        f["doc_id"]: score_filing(f["gold_transactions"], f["predicted_transactions"])
        for f in filings
    }
    overall = score_set(list(by_filing.values()))
    return {"by_filing": by_filing, "overall": overall}


def weakest_fields(scores: dict, *, n: int = 3) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda item: item[1])[:n]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = parser.parse_args()

    filings = load_gold_set()
    if not filings:
        print(f"no gold files found under {GOLD_DIR}", file=sys.stderr)
        raise SystemExit(1)

    report = score_gold_set(filings)
    extraction_errors = {
        f["doc_id"]: f["extraction_error"] for f in filings if f["extraction_error"] is not None
    }

    determinism_failures = []
    determinism_checked = 0
    for filing in filings:
        result = check_determinism(filing)
        if result is None:
            continue
        determinism_checked += 1
        if not result:
            determinism_failures.append(filing["doc_id"])

    if args.json:
        output = {
            **report,
            "extraction_errors": extraction_errors,
            "determinism_failures": determinism_failures,
        }
        print(json.dumps(output, indent=2))
        return

    print(f"Gold set: {len(filings)} filings (all kind=html)")
    print()
    header = f"{'field':<22}{'overall':>10}"
    print(header)
    print("-" * len(header))
    for field in SCORED_FIELDS:
        print(f"{field:<22}{report['overall'][field]:>10.2f}")
    print()

    failed = len(extraction_errors)
    if failed:
        print(
            f"NOTE: {failed}/{len(filings)} filings failed extraction entirely "
            "(see 'Extraction errors' below) — the column above is diluted by "
            "those as zero-scored, not a clean field-accuracy measurement."
        )
        print()

    print("Weakest fields overall:")
    for field, score in weakest_fields(report["overall"], n=3):
        print(f"  {field}: {score:.2f}")
    print()

    if extraction_errors:
        print("Extraction errors (scored as a total miss on that filing):")
        for doc_id, error in extraction_errors.items():
            print(f"  {doc_id}: {error}")
        print()
    if determinism_failures:
        print(f"DETERMINISM CHECK FAILED for: {', '.join(determinism_failures)}")
        raise SystemExit(1)
    print(
        f"Determinism check passed for all {determinism_checked} extractable filings "
        "(repeat run, identical output)."
    )
    if determinism_checked < len(filings):
        print(
            f"({len(filings) - determinism_checked} filings could not be checked: "
            "their extraction already failed.)"
        )


if __name__ == "__main__":
    main()
