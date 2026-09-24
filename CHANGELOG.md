# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Entries are added
under `Unreleased` in the PR that makes the change, and moved under a dated
heading when `development` is released to `master`.

## [Unreleased]

### Added

- `src/capitol_lake/stages/digital_extract.py`: digital House PDF extractor (ADR 0003) — `extract_digital` reads a text-layer PTR with `pypdf` into a silver `Filing` and its `Transaction` rows, anchoring each line on the `<type> <date> <date> <$range>` transaction line, walking backward for owner and asset description and forward over label-validated `Filing Status:`/`Subholding Of:`/`Description:` lines (whitespace stripped, NUL accepted as a wildcard for pypdf 6's garbled bold labels); a missing optional line is null at `LOW_CONFIDENCE`, never a positional guess. Page headers/footers are dropped so multi-page tables read through. `Transaction` gains optional `notification_date`, `filing_status`, `sub_owner`, `description` and a per-field `field_confidence` map; `pypdf` added as a dependency. Tests run on four real 2025 House PTR PDFs in `tests/fixtures/`, including one whose notification date precedes its transaction date (kept as printed).
- `src/capitol_lake/stages/senate_collect.py`: Senate collector — `route_filing_kind`/`parse_senate_index` route and filter a captured eFD search response (`POST /search/report/data/` JSON body, format confirmed against a real recorded response) to `/ptr/` entries with no network call, deriving each entry's year from its row (`/paper/` and every other report kind skipped, never fetched), and `collect_senate` orchestrates the rate-limited (~1 req/s) fetch-and-`bronze_write` loop over injected network/S3 callables, keyed by the filing's Senate eFD UUID (amendments as their own separate UUID); `handlers/senate_collect_handler.py` wires it to real `urllib`/`boto3` clients, with a `docker/senate_collect.Dockerfile` and `senate-collect-stage` compose service. Not scheduled (#18): the Senate eFD search UI is Akamai bot-protected — confirmed live to also block individual `/ptr/` pages and cookie-reuse via a plain HTTP client, only a real browser engine clears it (#23) — so the stage is invoked manually (or via a local headless-browser step) with a captured search response rather than discovering the index itself. `tests/fixtures/senate_ptr_sample.html` is a real fetched `/ptr/` filing page (captured the same session, via a headless-Chromium session that cleared the Akamai check), round-tripped byte-for-byte through `bronze_write` in a test — not just synthetic bytes.
- `src/capitol_lake/stages/house_collect.py`: House collector — `route_doc_id` classifies a doc id as digital (`20…`) or scanned (`82…`/`91…`) with no network call, `parse_house_index` parses the annual index ZIP into routed entries, and `collect_house` orchestrates the rate-limited (~1 req/s) fetch-and-`bronze_write` loop against fully injected network/S3 callables; `handlers/house_collect_handler.py` wires it to real `urllib`/`boto3` clients, with a `docker/house_collect.Dockerfile` and `house-collect-stage` compose service.
- `src/capitol_lake/schema.py`: silver-layer `Filing` and `Transaction` models — canonical `Owner`/`TransactionType` enums with raw-text fields, `(min, max)` `ValueRange`, an invariant-enforced `disclosure_lag`, a `ticker` slot for future resolution, and row-level `confidence`/`Provenance`.
- ADR 0010: FinOps decision — AWS Budget filtered by the `Project=capitol-lake` cost allocation tag, alert thresholds, and Terraform tagging scheme.
- `src/capitol_lake/` skeleton with the pure-function-plus-handler stage convention, a stub stage/handler pair, and shared bronze/silver S3 key-layout helpers.
- Local MinIO + Lambda Runtime Interface Emulator scaffold (`docker-compose.yml`, `docker/lambda.Dockerfile`) mirroring the intended S3 key layout, with conventions documented in `docs/local-dev.md`.
- `src/capitol_lake/stages/bronze_write.py`: chamber-agnostic bronze contract — a pure, hash-gated idempotent write decision (no-op on matching sha256, versioned `<doc_id>.<sha256[:8]>.<ext>` key on a different hash, original key never overwritten) plus the sidecar `.meta.json` payload; `bronze_versioned_key`/`bronze_meta_key` key helpers.

### Changed

- Project configured from the harness template: name, code standards, agent skills docs.
