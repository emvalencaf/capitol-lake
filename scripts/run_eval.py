#!/usr/bin/env -S uv run --project .
"""Run the extraction evaluator against the hand-labelled gold set.

Reads every `eval/gold/*.json` file, routes its matching PDF from
`eval/fixtures/<doc_id>.pdf` through the same digital/scanned extractor
`extract_house_filing` uses, scores the result against the gold
transactions (`capitol_lake.evaluation`), and prints a per-field report
macro-averaged by filing then by set, broken out by digital vs. scanned
(issue #40). Also runs the one-time determinism check: each filing is
extracted twice and the two runs must produce byte-identical rows.

Usage: `uv run scripts/run_eval.py [--json]`
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from capitol_lake.evaluation import (
    SCORED_FIELDS,
    score_gold_set,
    transaction_row_for_eval,
    weakest_fields,
)
from capitol_lake.stages.digital_extract import extract_digital
from capitol_lake.stages.extract import transaction_row
from capitol_lake.stages.house_collect import route_doc_id
from capitol_lake.stages.scanned_extract import extract_scanned

ROOT = Path(__file__).parent.parent
GOLD_DIR = ROOT / "eval" / "gold"
FIXTURES_DIR = ROOT / "eval" / "fixtures"

_EXTRACTORS = {"digital": extract_digital, "scanned": extract_scanned}


def _extract(doc_id: str, year: int) -> list[dict]:
    pdf_bytes = (FIXTURES_DIR / f"{doc_id}.pdf").read_bytes()
    bronze_key = f"bronze/house/year={year}/{doc_id}.pdf"
    kind = route_doc_id(doc_id)
    extraction = _EXTRACTORS[kind](pdf_bytes, bronze_key=bronze_key)
    return [transaction_row_for_eval(transaction_row(t)) for t in extraction.transactions]


def _extract_safe(doc_id: str, year: int) -> tuple[list[dict], str | None]:
    """`_extract`, but an extractor bug on one filing must not abort the whole report.

    A raised exception (e.g. a real-world amount shape the digital
    extractor's regex doesn't parse, discovered building this gold set) is
    treated as a total extraction failure: no predicted rows at all, which
    `score_filing` already scores as a miss on every gold field. The error
    is surfaced in the report rather than silently swallowed, since it's
    exactly the kind of weak spot this harness exists to find.
    """
    try:
        return _extract(doc_id, year), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def _check_determinism(doc_id: str, year: int) -> bool | None:
    """Two extraction runs of the same bytes must produce identical rows.

    Returns `None` (not applicable) when the filing doesn't extract at all,
    rather than counting a pre-existing extraction failure as a determinism
    failure too.
    """
    first, error = _extract_safe(doc_id, year)
    if error is not None:
        return None
    second, _ = _extract_safe(doc_id, year)
    return first == second


def load_gold_filings() -> tuple[list[dict], dict[str, str]]:
    filings = []
    extraction_errors: dict[str, str] = {}
    for path in sorted(GOLD_DIR.glob("*.json")):
        gold = json.loads(path.read_text())
        predicted, error = _extract_safe(gold["doc_id"], gold["year"])
        if error is not None:
            extraction_errors[gold["doc_id"]] = error
        filings.append(
            {
                "doc_id": gold["doc_id"],
                "kind": gold["kind"],
                "gold_transactions": [transaction_row_for_eval(t) for t in gold["transactions"]],
                "predicted_transactions": predicted,
            }
        )
    return filings, extraction_errors


def _print_report(report: dict) -> None:
    kinds = ("digital", "scanned", "overall")
    header = f"{'field':<22}" + "".join(f"{kind:>10}" for kind in kinds)
    print(header)
    print("-" * len(header))
    for field in SCORED_FIELDS:
        row = f"{field:<22}"
        for kind in kinds:
            scores = report["overall"] if kind == "overall" else report["by_kind"][kind]
            row += f"{scores[field]:>10.2f}"
        print(row)

    print()
    print("Weakest fields overall:")
    for field, score in weakest_fields(report["overall"], n=3):
        print(f"  {field}: {score:.2f}")
    print("Weakest fields, scanned:")
    for field, score in weakest_fields(report["by_kind"]["scanned"], n=3):
        print(f"  {field}: {score:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = parser.parse_args()

    gold_paths = sorted(GOLD_DIR.glob("*.json"))
    if not gold_paths:
        print(f"no gold files found under {GOLD_DIR}", file=sys.stderr)
        raise SystemExit(1)

    filings, extraction_errors = load_gold_filings()
    report = score_gold_set(filings)

    determinism_failures = []
    determinism_checked = 0
    for path in gold_paths:
        gold = json.loads(path.read_text())
        result = _check_determinism(gold["doc_id"], gold["year"])
        if result is None:  # extraction itself failed; not a determinism verdict
            continue
        determinism_checked += 1
        if not result:
            determinism_failures.append(gold["doc_id"])

    if args.json:
        output = {
            **report,
            "extraction_errors": extraction_errors,
            "determinism_failures": determinism_failures,
        }
        print(json.dumps(output, indent=2))
        return

    print(
        f"Gold set: {len(filings)} filings "
        f"({sum(1 for f in filings if f['kind'] == 'digital')} digital, "
        f"{sum(1 for f in filings if f['kind'] == 'scanned')} scanned)"
    )
    print()
    _print_report(report)
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


if __name__ == "__main__":
    main()
