#!/usr/bin/env -S uv run --project .
"""Run the extraction evaluator against the hand-labelled gold set.

Reads every `eval/gold/*.json` file, routes its matching PDF from
`eval/fixtures/<doc_id>.pdf` through the same digital/scanned extractor
`extract_house_filing` uses, scores the result against the gold
transactions (`extract_data.evaluation`), and prints a per-field report
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

from extract_data.digital_extract import extract_digital
from extract_data.evaluation import (
    SCORED_FIELDS,
    score_gold_set,
    transaction_row_for_eval,
    weakest_fields,
)
from extract_data.extract import transaction_row
from extract_data.scanned_extract import extract_scanned
from shared.doc_id import route_doc_id

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


def load_gold_set() -> list[dict]:
    """Load every gold file plus its extraction outcome, once each.

    Each item carries `doc_id`, `kind`, `year`, `gold_transactions`,
    `predicted_transactions` and `extraction_error` (`None` on success) —
    the single source both scoring and the determinism check read from, so
    neither re-globs nor re-parses `eval/gold/*.json` on its own.
    """
    filings = []
    for path in sorted(GOLD_DIR.glob("*.json")):
        gold = json.loads(path.read_text())
        predicted, error = _extract_safe(gold["doc_id"], gold["year"])
        filings.append(
            {
                "doc_id": gold["doc_id"],
                "kind": gold["kind"],
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
    on the first pass, rather than counting a pre-existing extraction
    failure as a determinism failure too.
    """
    if filing["extraction_error"] is not None:
        return None
    second, error = _extract_safe(filing["doc_id"], filing["year"])
    return error is None and filing["predicted_transactions"] == second


def _print_report(report: dict, filings: list[dict]) -> None:
    kinds = ("digital", "scanned", "overall")
    failed_by_kind = {
        kind: sum(1 for f in filings if f["kind"] == kind and f["extraction_error"] is not None)
        for kind in ("digital", "scanned")
    }
    total_by_kind = {
        kind: sum(1 for f in filings if f["kind"] == kind) for kind in ("digital", "scanned")
    }

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

    # A kind whose filings mostly failed to extract prints a score, but
    # that score measures extraction coverage, not field accuracy — say so
    # right next to the table, not only in eval/README.md prose, so the
    # report itself surfaces this rather than relying on a reader having
    # also read the docs (issue #40: "clearly surfaces which fields are
    # weak and for which filing type").
    for kind in ("digital", "scanned"):
        failed, total = failed_by_kind[kind], total_by_kind[kind]
        if failed:
            print(
                f"NOTE: {failed}/{total} {kind} filings failed extraction entirely "
                f"(see 'Extraction errors' below) — the {kind} column above is diluted "
                "by those as zero-scored, not a clean field-accuracy measurement."
            )
    if failed_by_kind["digital"] or failed_by_kind["scanned"]:
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
        if result is None:  # extraction itself failed; not a determinism verdict
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

    print(
        f"Gold set: {len(filings)} filings "
        f"({sum(1 for f in filings if f['kind'] == 'digital')} digital, "
        f"{sum(1 for f in filings if f['kind'] == 'scanned')} scanned)"
    )
    print()
    _print_report(report, filings)
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
