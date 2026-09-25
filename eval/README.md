# Extraction evaluation harness

Issue #40 (part of #30's spec, closing story #8/#24-#26): a stratified,
hand-labelled gold set of House PTR filings, and a metrics runner that scores
the rule-based extractor (`digital_extract`/`scanned_extract`) against it,
per field, macro-averaged by filing then by set, broken out by digital vs.
scanned.

## Layout

- `eval/fixtures/<doc_id>.pdf` — the 40 sampled House PTR PDFs (30 digital,
  10 scanned), fetched from the House Clerk's public financial-disclosure
  site. `manifest.json` records each fixture's `doc_id`/`year`/`kind`.
- `eval/gold/<doc_id>.json` — one hand-labelled gold file per fixture. See
  "Gold record format" below.
- `scripts/run_eval.py` — the metrics runner: `uv run scripts/run_eval.py`.

## Sampling

40 filings, 30 digital / 10 scanned, sampled from the House Clerk's annual
index across four years (2021, 2023, 2024, 2025) so the set spans well over
the required minimum of two years and isn't biased toward one form
template. Selection was randomized within each year/kind pool (`random.seed
(40)`) after excluding filings already used as extractor unit-test fixtures
in `tests/fixtures/` (those are reused here as part of the 40, not
duplicated).

## Gold record format

```json
{
  "doc_id": "20030646",
  "kind": "digital",
  "year": 2025,
  "transactions": [
    {
      "line_no": 1,
      "owner": "self",
      "transaction_type": "purchase",
      "asset_type": "stock",
      "asset_description": "Apple Inc. - Common Stock",
      "transaction_date": "2025-01-15",
      "value_min": 1001,
      "value_max": 15000,
      "notification_date": "2025-01-20",
      "filing_status": null,
      "sub_owner": null,
      "description": null
    }
  ]
}
```

Each `transactions[]` entry mirrors the scored subset of the silver
`Transaction` schema (`capitol_lake.schema.Transaction`), `line_no`
numbered in document order. Digital filings were labelled from pypdf's own
generic `extract_text()` output (independent of this project's structural
parser, so the gold set isn't circular against the code it scores).
Scanned filings have no text layer and this environment has no working
`tesseract` install, so they were labelled visually from rasterized page
images (`pypdfium2`) — including reading the paper form's `transaction_type`
and dollar-bracket checkboxes by eye, which the extractor itself cannot do
(ADR 0002) and is expected to score near zero on.

## Scored fields

`capitol_lake.evaluation.SCORED_FIELDS`, all at the `Transaction` level:
`owner`, `transaction_type`, `asset_type`, `asset_description`,
`transaction_date`, `value_min`, `value_max`, `notification_date`,
`filing_status`, `sub_owner`, `description`.

Excluded, per the issue's acceptance criteria:

- **Ticker fields** (`Transaction.ticker`) — resolved by a separate cascade
  (OpenFIGI + EDGAR, #39) with its own accept/reject logic; scoring it here
  would conflate two different extraction strategies under one metric.
- **Metadata fields** — everything on `Filing` (`filer_name`, `filing_date`,
  `year`, `chamber`, `doc_id`) plus `Transaction.confidence`/`provenance`/
  `disclosure_lag` (derived, not extracted) and `line_no` (structural, used
  only to align gold and predicted rows).

`owner`/`transaction_type`/`asset_type`/dates/dollar amounts are scored by
exact match (both `null` counts as a match; one `null` and one non-`null`
is a total miss). `asset_description`/`filing_status`/`sub_owner`/
`description` are scored by a continuous text-similarity ratio
(`difflib.SequenceMatcher`), so a near-miss free-text field isn't scored
identically to a completely wrong one.

## Averaging

`capitol_lake.evaluation.score_filing` averages each field's score across
one filing's gold transactions (a gold row with no matching predicted
`line_no` scores 0.0 on every field — a missed row is a total miss).
`score_set` then averages filing-level scores within a set (digital,
scanned, or overall) — the two-level "macro-averaged by filing then by set"
the issue asks for, so one filing with unusually many rows can't dominate
the set's score.

## Determinism check

`scripts/run_eval.py` also runs each filing's extractor twice on the same
bytes and asserts the two runs produce byte-identical rows (`transaction_row`
output, field by field) — the one-time check the issue asks for, not an
ongoing tracked metric. As of this writing it passes for every digital
filing in the gold set. It could not be executed here for scanned filings,
since `extract_scanned` requires a `tesseract` binary this sandboxed
environment doesn't have installed (`apt`/`sudo` are both unavailable); both
extractors are pure functions over their input bytes with no randomness or
wall-clock dependence, so the same guarantee is expected to hold — this
should be re-run and confirmed in an environment with `tesseract` installed
(e.g. CI, which already installs it for `test_scanned_extract.py`) before
treating the scanned-side determinism claim as verified rather than
expected.

## Running

```bash
uv run scripts/run_eval.py          # human-readable report
uv run scripts/run_eval.py --json   # raw {by_filing, by_kind, overall} scores
```

A single filing whose extractor raises (rather than returning rows) is
scored as a total miss on every gold field for that filing — not a crash
of the whole report — and listed under "Extraction errors" in the output.
When enough of a set's filings fail extraction to meaningfully dilute its
column, the report prints a `NOTE:` line directly under the score table
naming how many failed and pointing at the reason, rather than leaving a
diluted-but-plausible-looking number to be misread as a real field-accuracy
score.

## Findings from the first run (2026-09-24)

```
field                    digital   scanned   overall
----------------------------------------------------
owner                       0.93      0.10      0.72
transaction_type            0.93      0.10      0.72
asset_type                  0.93      0.10      0.72
transaction_date            0.93      0.10      0.72
value_min                   0.93      0.10      0.72
value_max                   0.93      0.10      0.72
notification_date           0.93      0.10      0.72
asset_description           0.86      0.10      0.67
filing_status               0.93      0.10      0.72
sub_owner                   0.93      0.10      0.72
description                 0.93      0.10      0.72
```

**The scanned column is not a real accuracy measurement.** This sandbox has
no `tesseract` binary installed (no `sudo`/`apt` access), so every one of
the 10 scanned filings fails with `TesseractNotFoundError` before
`extract_scanned` produces a single row — the uniform 0.10 across every
scanned field is 9 total-extraction-failures-as-zero plus 1 filing
(`8220717`, a legitimate "nothing to report" PTR with zero gold
transactions) scoring 1.0, averaged: `(9*0 + 1*1)/10 = 0.10`. **Re-run
`uv run scripts/run_eval.py` in an environment with `tesseract` installed
(CI already installs it for `test_scanned_extract.py`) to get the real
scanned-vs-digital breakdown this issue asks for**, before drawing any
conclusion from these numbers about `transaction_type`/`value_range` being
genuinely unrecoverable on scanned filings (ADR 0002 already expects that
for those two specific fields, but not for the row failing to extract at
all).

**Digital column, real finding**: 2 of 30 digital filings (`20022260`,
`20023819`) fail extraction entirely — `parse_value_range` doesn't handle a
literal (non-bracket) dollar amount like `$9.00`, which two real 2023
filings print for a small-value line. Filed as issue #57 rather than fixed
here (#40 is a read-only consumer of the current extractors). Excluding
those two crashes, the other 28 digital filings' per-field scores are
close to 1.0 across the board; `asset_description`'s 0.86 is the field
most worth a closer look — it's the only similarity-scored (not
exact-match) field with meaningfully sub-1.0 signal on digital filings.

Determinism check: passed for all 28 digital filings that extracted
successfully (30 digital minus the 2 that crash per #57); not applicable
to those 2 crashing digital filings or the 10 scanned ones (no
`tesseract`) in this environment — re-run once #57 is fixed and
`tesseract` is available to get a determinism verdict on the full 40.
