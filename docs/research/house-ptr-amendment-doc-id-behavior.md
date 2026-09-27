# House PTR amendment DocID behavior: primary-source check

## Question

`src/house_collect/collect.py` re-fetches and hash-compares every filing's
PDF on every run (via `src/shared/bronze_write.py`'s hash-gated write),
purely as a defense against the possibility that the House Clerk
republishes the **same DocID** with **different PDF bytes** (e.g. a silent
correction to an already-indexed Periodic Transaction Report). This is a
factual check of that possibility against the House Clerk's own primary
sources: does a PTR correction get a **new DocID** (a distinct row in the
annual `{year}FD.zip` index, a brand-new filing), or can the Clerk reuse an
existing DocID for revised content?

## Primary sources consulted

1. **The PTR form and instructions themselves** —
   `https://ethics.house.gov/wp-content/uploads/2026/02/Final-CY-2025-PTR-Form-1.pdf`
   ("ETHICS IN GOVERNMENT ACT PERIODIC TRANSACTION REPORT FORM AND
   INSTRUCTIONS", CY2025 edition).
2. **The Committee on Ethics' Instruction Guide** —
   `https://ethics.house.gov/wp-content/uploads/2026/07/7-8-2026-2025-Published-Instruction-Guide.pdf`
   ("2026 Instruction Guide, Financial Disclosure Reports for Calendar Year
   2025"), specifically its "Timeliness of Filings" and "Committee Review"
   sections.
3. **The actual annual index ZIP and its XML**, fetched live from
   `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2025FD.zip`
   (`2025FD.xml`, `<Member>` rows with `DocID`/`FilingType`/`FilingDate`
   fields) — this is the exact artifact `src/house_collect/collect.py`
   parses in production.
4. **Individual filing PDFs** fetched live by DocID from
   `https://disclosures-clerk.house.gov/public_disc/{ptr-pdfs,financial-pdfs}/{year}/{doc_id}.pdf`
   — these are the Clerk's own rendered documents, which embed a `Filing
   Status`/`Filing Type` field and a `Filing ID #` on the page itself.

No secondary sources (blog posts, scraper READMEs, news write-ups) are
cited as evidence for any claim below; a couple came up in search results
and are explicitly excluded.

## Findings

**1. The PTR form has a dedicated Initial-Report-vs-Amendment field, and an
amendment is filed as a new submission, not an edit to the original.**
Page 5 of the PTR form (source 1) has a checkbox: `Initial Report` /
`Amendment`, plus `Date of Report Being Amended: ______`. The instruction
text on page 3 of the same PDF states: *"The PTR (and any amendments) must
be filed with the Clerk of the House of Representatives... "* — treating
"the PTR" and "amendments" as separate filed items, each independently
submitted (with its own original signature, per the same page: *"THE
PERIODIC TRANSACTION REPORT MUST BE SIGNED AND DATED BY THE REPORTING
INDIVIDUAL"* applies per-submission).

**2. The Instruction Guide confirms amendments are new, separately
published filings, not in-place edits.** From source 2 ("Committee
Review" section): *"Unintentional errors and omissions in FDs and PTRs are
an ordinary part of the process for many filers... Amending FDs or PTRs is
the most common method used to address unintentional errors or omissions.
**Amendments are publicly available in the same manner as the original FDs
or PTRs they amend.**"* And: *"Filing an amendment on a paper form requires
the same number of copies as the original filing. An amendment may be in
the form of a revised FD or PTR (indicating where appropriate that it is an
amendment) or by an explanatory letter..."* The same guide also states the
Clerk's public-website posting obligation as: *"Copies of **all** FDs and
**amendments** filed by Members and Candidates"* (a "General Information"
section) — treating amendments as their own postable items alongside, not
overwriting, originals.

**3. Direct confirmation from a live document: an amendment carries its own
distinct Filing ID, separate from the filing it amends.** Fetching
`2025FD.xml` from the live `2025FD.zip` and filtering the `FilingType`
field turned up code `A` (119 rows in the 2025 index; other codes present:
`B`, `C`, `D`, `E`, `G`, `H`, `O`, `P`, `T`, `W`, `X` — the index itself
gives no field spelling out what each letter means). Fetching the actual
PDF for one `FilingType=A` row (`DocID 10073311`, filer Jamie Peterson
Ager) from
`https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2025/10073311.pdf`
shows, verbatim on the page: `Filing Type: Amendment Report`, `Filing Year:
2025`, `Filing Date: 02/02/2026`, and `Filing ID #10073311` — i.e. the
amendment itself is a complete, standalone filing with its own Filing
ID/DocID (`10073311`), matching the DocID it's indexed under. This document
does not display the DocID of the report it amends anywhere on its face.

**4. PTR PDFs embed an explicit `Filing Status` field whose observed value
is `New`.** Every PTR PDF sampled during this check (10 additional DocIDs
plus the one referenced in `src/house_collect/collect.py`'s own docstring
context — see reproduction below) showed `Filing Status: New` in its header
block. None of the sampled PTRs happened to be an amendment, so this check
did not turn up a live example of `Filing Status: Amendment` on a PTR
specifically — but combined with finding 3 (the FD-side "Amendment Report"
example) and the PTR form's own Initial/Amendment checkbox (finding 1),
this is the same field family, populated per-submission, not mutated after
the fact.

**5. Within a single year's index, no DocID collisions were observed
across an individual's repeated PTR filings.** Filtering `2025FD.txt` (the
flat, tab-delimited companion to the XML, same index ZIP) for members with
multiple `FilingType=P` rows shows every monthly/periodic PTR they filed
getting its own distinct `DocID` (e.g. Rep. Josh Gottheimer: 12 separate
PTR DocIDs across 2025, each with a distinct `FilingDate`). This is
consistent with — though does not by itself prove — "one submission, one
DocID" as the Clerk's operative model.

**Reproduction**: the exact commands used to fetch and inspect the index
and sample PDFs (`curl`, `unzip`, `pypdf` text extraction) are not checked
into this repo; they were ad hoc against the live URLs above on
2026-09-26. Re-running `curl -sL -o 2025FD.zip
https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2025FD.zip`
and inspecting `2025FD.xml`/`2025FD.txt` reproduces finding 5; fetching any
`FilingType=A` DocID's PDF from `financial-pdfs/{year}/{doc_id}.pdf`
reproduces finding 3.

## Answer, with confidence level

**A House Clerk correction/amendment gets its own new DocID — it is filed,
published, and indexed as a distinct entry, not a same-DocID content
overwrite of the original.** Confidence: **high**, based on the convergence
of (a) the PTR form's own initial/amendment submission model, (b) the
Instruction Guide's explicit "amendments are publicly available in the
same manner as the originals" and "copies of all FDs and amendments"
language, (c) a live, directly-observed amendment document (`DocID
10073311`) that is itself a complete standalone filing with its own Filing
ID, and (d) no DocID collisions observed anywhere in a full year's index.

**What remains explicitly unconfirmed**: no primary source — not the PTR
form, not the Instruction Guide, not the index ZIP's field list (which has
no documented schema/data-dictionary beyond the field names themselves) —
makes a flat, unconditional statement such as *"a DocID, once issued, is
never reused or altered."* This project did not find or fetch a live
example of an *amended PTR specifically* (as opposed to an amended annual
FD) to directly confirm its `Filing Status: Amendment` value and its
DocID's independence from the original PTR's DocID — findings 3 and 4
together make this a reasonable, but not fully closed, inference for the
PTR case specifically. **No primary source was found that documents or
permits same-DocID content replacement**; that scenario is not affirmed
anywhere, but its absence from the documentation is not the same as an
explicit denial. If eliminating the hash-compare re-fetch in
`src/house_collect/collect.py` is being considered, that residual gap (no
explicit "DocIDs are immutable and never reused" guarantee, and no directly
observed amended-PTR example) is the honest boundary of what this check
established.

## Senate eFD contrast (context only, not deep-researched)

`src/senate_collect/collect.py`'s own comment (lines ~49-50) states: *"A
filing's UUID (and an amendment's own, separate UUID) is used as `doc_id`
unchanged..."` — i.e. this repo's existing, undocumented assumption is that
Senate eFD amendments get their own UUID distinct from the original. A
cheap search for a Senate-side primary source confirming or refuting this
(official eFD/`efdsearch.senate.gov` documentation, `ethics.senate.gov` PTR
instructions) did not turn up a document that states this explicitly one
way or the other within the scope of this check — the Senate PTR
instructions PDF found
(`https://www.ethics.senate.gov/public/_cache/files/df29d914-0b9c-4431-b09e-bdea62dc7e56/2020-periodic-transaction-report-instructions.pdf`)
was not fetched/read in this pass. This repo's Senate-side comment is
therefore still an internal, unverified assumption, not something this
check independently confirmed — consistent with how the task scoped this
(House question is the priority; Senate is a note, not a finding).
