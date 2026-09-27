#!/usr/bin/env -S uv run --project .
"""Run the extraction evaluator against the hand-labelled gold set.

Reads every `eval/gold/*.json` file, routes its matching PDF from
`eval/fixtures/<doc_id>.pdf` through an extractor, scores the result against
the gold transactions (`extract_data.evaluation`), and prints a per-field
report macro-averaged by filing then by set, broken out by digital vs.
scanned (issue #40).

Two extractors are available (`--extractor`):

- `tesseract` (default): the same digital/scanned rule-based extractors
  `extract_house_filing` uses. Also runs the one-time determinism check:
  each filing is extracted twice and the two runs must produce
  byte-identical rows.
- `llm`: the benchmark-only `extract_llm` (#89), reading transactions
  directly via a `--provider` (`groq`/`gemini`/`lm_studio`). LLM output isn't
  deterministic, so the determinism check is skipped for it and replaced by
  an optional consistency check (`--llm-runs`, ADR 0019): repeat each
  filing's extraction and report how much the repeats agree with each
  other, per field and overall, instead of requiring them to be identical.

`--sample N` runs against a seeded random subset of the gold set instead of
all of it, for cheaper iteration against a real (rate-limited, metered)
LLM provider.

Usage: `uv run scripts/run_house_eval.py [--json]`
       `uv run scripts/run_house_eval.py --extractor llm --provider groq --llm-runs 3`
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extract_data.digital_extract import extract_digital
from extract_data.evaluation import (
    SCORED_FIELDS,
    consistency_set,
    score_gold_set,
    score_set,
    transaction_row_for_eval,
    weakest_fields,
)
from extract_data.extract import transaction_row
from extract_data.llm_extract import extract_llm
from extract_data.scanned_extract import extract_scanned
from shared.doc_id import route_doc_id
from shared.llm_providers import Provider, provider_by_name

ROOT = Path(__file__).parent.parent
GOLD_DIR = ROOT / "eval" / "gold"
FIXTURES_DIR = ROOT / "eval" / "fixtures"

_EXTRACTORS = {"digital": extract_digital, "scanned": extract_scanned}

# Fixed so `--sample` picks the same subset across runs of the same size,
# rather than a fresh gamble on cost/coverage each invocation.
_SAMPLE_SEED = 0

Extractor = Callable[..., Any]


def _tesseract_extractor(pdf_bytes: bytes, *, bronze_key: str) -> Any:
    doc_id = bronze_key.rsplit("/", 1)[-1].split(".")[0]
    return _EXTRACTORS[route_doc_id(doc_id)](pdf_bytes, bronze_key=bronze_key)


_MODEL_ENV_VAR = {"groq": "GROQ_MODEL", "gemini": "GEMINI_MODEL", "lm_studio": "LM_STUDIO_MODEL"}


def _llm_extractor(args: argparse.Namespace) -> Extractor:
    provider_name = args.provider or os.environ.get("LLM_FALLBACK_PROVIDER", "lm_studio")
    if args.model:
        os.environ[_MODEL_ENV_VAR[provider_name]] = args.model
    provider: Provider = provider_by_name(provider_name)
    return functools.partial(extract_llm, provider=provider, input_mode=args.llm_input)


def _extract(extractor: Extractor, doc_id: str, year: int) -> list[dict]:
    pdf_bytes = (FIXTURES_DIR / f"{doc_id}.pdf").read_bytes()
    bronze_key = f"bronze/house/year={year}/{doc_id}.pdf"
    extraction = extractor(pdf_bytes, bronze_key=bronze_key)
    return [transaction_row_for_eval(transaction_row(t)) for t in extraction.transactions]


def _extract_safe(extractor: Extractor, doc_id: str, year: int) -> tuple[list[dict], str | None]:
    """`_extract`, but an extractor bug or provider failure on one filing must not abort the report.

    A raised exception (a real-world amount shape the digital extractor's
    regex doesn't parse; a Groq rate limit; an LM Studio server that isn't
    running) is treated as a total extraction failure: no predicted rows at
    all, which `score_filing` already scores as a miss on every gold field.
    The error is surfaced in the report rather than silently swallowed,
    since it's exactly the kind of weak spot this harness exists to find —
    for the `llm` extractor, that includes a provider's real reliability
    (ADR 0019), not only a rule-based extractor's parsing bugs.
    """
    try:
        return _extract(extractor, doc_id, year), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def load_gold_set(extractor: Extractor, *, sample: int | None) -> list[dict]:
    """Load every gold file plus its extraction outcome, once each.

    Each item carries `doc_id`, `kind`, `year`, `gold_transactions`,
    `predicted_transactions` and `extraction_error` (`None` on success) —
    the single source both scoring and the determinism/consistency check
    read from, so neither re-globs nor re-parses `eval/gold/*.json` on its
    own. `sample`, when given, keeps a fixed-seed random subset of the gold
    files instead of all of them (before any extraction runs, so a smaller
    sample also means fewer provider calls).
    """
    paths = sorted(GOLD_DIR.glob("*.json"))
    if sample is not None and sample < len(paths):
        paths = random.Random(_SAMPLE_SEED).sample(paths, sample)

    filings = []
    for path in paths:
        gold = json.loads(path.read_text())
        predicted, error = _extract_safe(extractor, gold["doc_id"], gold["year"])
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


def check_determinism(extractor: Extractor, filing: dict) -> bool | None:
    """Two extraction runs of the same bytes must produce identical rows.

    Returns `None` (not applicable) when the filing didn't extract at all
    on the first pass, rather than counting a pre-existing extraction
    failure as a determinism failure too. Only meaningful for a deterministic
    extractor (`tesseract`); the `llm` extractor uses `consistency_scores`
    instead (ADR 0019).
    """
    if filing["extraction_error"] is not None:
        return None
    second, error = _extract_safe(extractor, filing["doc_id"], filing["year"])
    return error is None and filing["predicted_transactions"] == second


def consistency_scores(extractor: Extractor, filing: dict, runs: int) -> dict[str, float] | None:
    """`runs` total extractions of `filing`, averaged pairwise per field (ADR 0019).

    Returns `None` when the filing's first-pass extraction already failed
    (nothing to compare), or when a repeat run's extraction fails (a failed
    repeat isn't a consistency verdict, it's a reliability one already
    covered by `extraction_error`/the report's failure counts).
    """
    if filing["extraction_error"] is not None:
        return None
    attempts = [filing["predicted_transactions"]]
    for _ in range(runs - 1):
        predicted, error = _extract_safe(extractor, filing["doc_id"], filing["year"])
        if error is not None:
            return None
        attempts.append(predicted)
    return consistency_set(attempts)


def _print_field_table(by_kind: dict[str, dict[str, float]], *, title: str | None = None) -> None:
    kinds = ("digital", "scanned", "overall")
    header = f"{'field':<22}" + "".join(f"{kind:>10}" for kind in kinds)
    if title is not None:
        print(title)
    print(header)
    print("-" * len(header))
    for field in SCORED_FIELDS:
        row = f"{field:<22}"
        for kind in kinds:
            scores = by_kind.get(kind)
            row += f"{scores[field]:>10.2f}" if scores else f"{'n/a':>10}"
        print(row)
    print()


def _print_report(report: dict, filings: list[dict]) -> None:
    failed_by_kind = {
        kind: sum(1 for f in filings if f["kind"] == kind and f["extraction_error"] is not None)
        for kind in ("digital", "scanned")
    }
    total_by_kind = {
        kind: sum(1 for f in filings if f["kind"] == kind) for kind in ("digital", "scanned")
    }

    accuracy_by_kind = {**report["by_kind"], "overall": report["overall"]}
    _print_field_table(accuracy_by_kind)

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


def _consistency_report(
    extractor: Extractor, filings: list[dict], runs: int
) -> dict[str, dict[str, float]]:
    by_kind: dict[str, list[dict[str, float]]] = {"digital": [], "scanned": []}
    for filing in filings:
        scores = consistency_scores(extractor, filing, runs)
        if scores is not None:
            by_kind[filing["kind"]].append(scores)
    result = {kind: score_set(scores) for kind, scores in by_kind.items() if scores}
    checked = [score for scores in by_kind.values() for score in scores]
    if checked:
        result["overall"] = score_set(checked)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    parser.add_argument(
        "--extractor",
        choices=("tesseract", "llm"),
        default="tesseract",
        help="which extractor to benchmark (default: tesseract)",
    )
    parser.add_argument(
        "--provider",
        choices=("groq", "gemini", "lm_studio"),
        default=None,
        help="LLM provider for --extractor llm (default: $LLM_FALLBACK_PROVIDER or lm_studio)",
    )
    parser.add_argument("--model", default=None, help="override the provider's default model")
    parser.add_argument(
        "--llm-input",
        choices=("text", "vision"),
        default="text",
        dest="llm_input",
        help="scanned-filing input for --extractor llm: OCR text or the page image",
    )
    parser.add_argument(
        "--llm-runs",
        type=int,
        default=1,
        help="repeat each filing's --extractor llm extraction N times and report consistency",
    )
    parser.add_argument(
        "--sample", type=int, default=None, help="benchmark a seeded random subset of N filings"
    )
    args = parser.parse_args()

    extractor = _tesseract_extractor if args.extractor == "tesseract" else _llm_extractor(args)

    filings = load_gold_set(extractor, sample=args.sample)
    if not filings:
        print(f"no gold files found under {GOLD_DIR}", file=sys.stderr)
        raise SystemExit(1)

    report = score_gold_set(filings)
    extraction_errors = {
        f["doc_id"]: f["extraction_error"] for f in filings if f["extraction_error"] is not None
    }

    determinism_failures: list[str] | None = None
    determinism_checked = 0
    consistency: dict[str, dict[str, float]] | None = None

    if args.extractor == "tesseract":
        determinism_failures = []
        for filing in filings:
            result = check_determinism(extractor, filing)
            if result is None:  # extraction itself failed; not a determinism verdict
                continue
            determinism_checked += 1
            if not result:
                determinism_failures.append(filing["doc_id"])
    elif args.llm_runs > 1:
        consistency = _consistency_report(extractor, filings, args.llm_runs)

    if args.json:
        output: dict[str, Any] = {**report, "extraction_errors": extraction_errors}
        if determinism_failures is not None:
            output["determinism_failures"] = determinism_failures
        else:
            output["determinism"] = "not applicable (llm extractor; see consistency)"
        if consistency is not None:
            output["consistency"] = consistency
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

    if consistency is not None:
        _print_field_table(consistency, title=f"Consistency across {args.llm_runs} runs:")

    if determinism_failures is None:
        if args.llm_runs <= 1:
            print("Determinism check: not applicable for --extractor llm (use --llm-runs > 1).")
        return
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
