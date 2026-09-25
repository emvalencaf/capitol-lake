"""One-time determinism check (issue #40): repeat runs must be byte-identical.

Not an ongoing tracked metric — a single pass/fail check that the rule-based
extractors, as pure functions of their input bytes, never vary run to run.
`scripts/run_eval.py` reruns this same check across the whole 40-filing gold
set; these tests pin it as a regular part of the suite for the two fixtures
already exercised elsewhere.
"""

import shutil
from pathlib import Path

import pytest

from capitol_lake.stages.digital_extract import extract_digital
from capitol_lake.stages.extract import transaction_row
from capitol_lake.stages.scanned_extract import extract_scanned

FIXTURES = Path(__file__).parent / "fixtures"

requires_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract not installed in this environment"
)


def test_digital_extraction_is_deterministic_across_repeat_runs():
    pdf_bytes = (FIXTURES / "house_digital_20030646.pdf").read_bytes()
    bronze_key = "bronze/house/year=2025/20030646.pdf"

    first = extract_digital(pdf_bytes, bronze_key=bronze_key)
    second = extract_digital(pdf_bytes, bronze_key=bronze_key)

    assert first.filing == second.filing
    assert [transaction_row(t) for t in first.transactions] == [
        transaction_row(t) for t in second.transactions
    ]


@requires_tesseract
def test_scanned_extraction_is_deterministic_across_repeat_runs():
    pdf_bytes = (FIXTURES / "house_scanned_8217884.pdf").read_bytes()
    bronze_key = "bronze/house/year=2021/8217884.pdf"

    first = extract_scanned(pdf_bytes, bronze_key=bronze_key)
    second = extract_scanned(pdf_bytes, bronze_key=bronze_key)

    assert first.filing == second.filing
    assert [transaction_row(t) for t in first.transactions] == [
        transaction_row(t) for t in second.transactions
    ]
