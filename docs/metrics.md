# Extraction metrics

Part of #75. This page reports current extraction-accuracy numbers for the
House and Senate extractors, sourced from the `eval/` harness (see
[eval/README.md](../eval/README.md)) and `CHANGELOG.md`.

**These are eval-harness/gold-set scores, not production telemetry.** They
come from `uv run scripts/run_eval.py` and `uv run scripts/run_senate_eval.py`
scoring the extractors against hand-labelled gold sets of real filings
sampled offline. **The pipeline has never executed against real AWS
infrastructure** — no Lambda has run in a deployed account, no CloudWatch
metric exists, and no number on this page reflects a live invocation. See
[cost.md](cost.md)'s "Average invocation duration is not measured" note for
the same caveat applied to cost instead of accuracy.

## House (`digital_extract` / `scanned_extract`)

Per-field score, macro-averaged by filing then by set (`eval/README.md`'s
"Averaging" section), re-run 2026-09-26 for this page (`uv run
scripts/run_eval.py`), 40 filings (30 digital, 10 scanned). This supersedes
the numbers in `eval/README.md`'s own "Findings" section, which record its
first run (2026-09-24) and predate #57's fix (merged via #65): that section
is now a stale historical snapshot, not the current score.

| field | digital | scanned | overall |
|---|---|---|---|
| owner | 1.00 | 0.10 | 0.78 |
| transaction_type | 1.00 | 0.10 | 0.78 |
| asset_type | 1.00 | 0.10 | 0.78 |
| transaction_date | 1.00 | 0.10 | 0.78 |
| value_min | 1.00 | 0.10 | 0.78 |
| value_max | 1.00 | 0.10 | 0.78 |
| notification_date | 1.00 | 0.10 | 0.78 |
| asset_description | 0.92 | 0.10 | 0.72 |
| filing_status | 1.00 | 0.10 | 0.78 |
| sub_owner | 1.00 | 0.10 | 0.78 |
| description | 1.00 | 0.10 | 0.78 |

### The scanned column is not a real accuracy figure

The uniform 0.10 across every scanned field is a tesseract-absence
artifact, not a measurement of `scanned_extract`'s ability to read a form.
The sandbox that produced this run has no `tesseract` binary installed (no
`sudo`/`apt` access), so all 10 scanned filings raise
`TesseractNotFoundError` before `extract_scanned` produces a single row.
Scored as a total miss, 9 of the 10 filings contribute 0.0 and 1 filing
(`8220717`, a legitimate "nothing to report" PTR with zero gold
transactions) contributes 1.0: `(9*0 + 1*1)/10 = 0.10` on every field,
identically, regardless of what that field actually is. This is an
extraction-failure artifact of the environment, not signal about
`transaction_type` or `value_range` being unrecoverable on scanned forms
(ADR 0002 already expects that for those two fields specifically, on rows
that do extract) or about any other field's real accuracy on scanned
filings.

CI already installs `tesseract` for `test_scanned_extract.py`, so re-running
`uv run scripts/run_eval.py` there would produce a real scanned-vs-digital
breakdown. That has not been done as of this writing; **there is currently
no real accuracy number for scanned House filings**, only this artifact.

### Digital column

All 30 digital filings now extract successfully and score a perfect 1.00 on
every exact-match field. Per `CHANGELOG.md`'s `#57` entry, `parse_value_range`
now accepts a bare literal (non-bracket) dollar amount like `$9.00` instead
of failing the whole filing's extraction with `unreadable amount` — the gap
that previously crashed 2 of the 30 digital filings (`20022260`,
`20023819`) entirely, before `eval/README.md`'s first-run snapshot was
written. `asset_description` at 0.92 is the only field below 1.0: it's the
sole similarity-scored (not exact-match) field, so a near-miss free-text
match still counts against it even though the row itself extracted
correctly.

## Senate (`extract_senate_filing`)

Per-field score, same `capitol_lake.evaluation` machinery, from the first
run (2026-09-26), 40 real `/ptr/` filings fetched live from
`efdsearch.senate.gov`. Senate has no digital/scanned split (ADR 0013: every
Senate fixture is `kind == "html"`), so this reports one overall column, not
three:

| field | overall |
|---|---|
| owner | 1.00 |
| transaction_type | 1.00 |
| asset_type | 1.00 |
| transaction_date | 1.00 |
| value_min | 1.00 |
| value_max | 1.00 |
| notification_date | 1.00 |
| asset_description | 1.00 |
| filing_status | 1.00 |
| sub_owner | 1.00 |
| description | 1.00 |

All 40 filings extracted successfully and scored a perfect 1.00 on every
field. `notification_date`/`filing_status`/`sub_owner` do so trivially: per
ADR 0013, both gold and predicted are always null for Senate, so this metric
never actually exercises them on real values. This is a gold-set score
against 40 hand-labelled fixtures, not a production accuracy claim; the
Senate extractor, like the House one, has never run against real AWS
infrastructure.

## Determinism

`scripts/run_eval.py` and `scripts/run_senate_eval.py` also run each
filing's extractor twice on the same bytes and assert byte-identical output
(a one-time check, not an ongoing tracked metric):

- **House**: passed for all 30 digital filings (all now extract
  successfully; see #57 above). Not applicable to the 10 scanned filings —
  no `tesseract` binary in the sandbox that produced this run, so
  `extract_scanned` never gets past `TesseractNotFoundError` to produce
  output to compare.
- **Senate**: passed for all 40 filings.

## Scored fields and averaging

Both harnesses score the same 11 `Transaction`-level fields
(`capitol_lake.evaluation.SCORED_FIELDS`): `owner`, `transaction_type`,
`asset_type`, `asset_description`, `transaction_date`, `value_min`,
`value_max`, `notification_date`, `filing_status`, `sub_owner`,
`description`. Ticker fields and everything on `Filing` are excluded — see
`eval/README.md`'s "Scored fields" section for why. Exact-match fields
(owner, type, dates, dollar amounts) score 0/1; free-text fields
(`asset_description`, `filing_status`, `sub_owner`, `description`) score a
continuous text-similarity ratio, so a near-miss isn't scored identically to
a completely wrong value. A gold row with no matching predicted row scores
0.0 on every field for that row.

## Reproducing these numbers

```bash
uv run scripts/run_eval.py            # House: human-readable report
uv run scripts/run_eval.py --json     # House: raw {by_filing, by_kind, overall}
uv run scripts/run_senate_eval.py     # Senate: human-readable report
```

Both are read-only over the committed gold sets under `eval/fixtures/`,
`eval/gold/`, `eval/senate_fixtures/`, and `eval/senate_gold/` — no network
access or AWS credentials required to reproduce them.
