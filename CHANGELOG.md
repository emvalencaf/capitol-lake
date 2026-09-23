# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Entries are added
under `Unreleased` in the PR that makes the change, and moved under a dated
heading when `development` is released to `master`.

## [Unreleased]

### Added

- `src/capitol_lake/stages/house_collect.py`: House collector — `route_doc_id` classifies a doc id as digital (`20…`) or scanned (`82…`/`91…`) with no network call, `parse_house_index` parses the annual index ZIP into routed entries, and `collect_house` orchestrates the rate-limited (~1 req/s) fetch-and-`bronze_write` loop against fully injected network/S3 callables; `handlers/house_collect_handler.py` wires it to real `urllib`/`boto3` clients, with a `docker/house_collect.Dockerfile` and `house-collect-stage` compose service.
- `src/capitol_lake/schema.py`: silver-layer `Filing` and `Transaction` models — canonical `Owner`/`TransactionType` enums with raw-text fields, `(min, max)` `ValueRange`, an invariant-enforced `disclosure_lag`, a `ticker` slot for future resolution, and row-level `confidence`/`Provenance`.
- ADR 0010: FinOps decision — AWS Budget filtered by the `Project=capitol-lake` cost allocation tag, alert thresholds, and Terraform tagging scheme.
- `src/capitol_lake/` skeleton with the pure-function-plus-handler stage convention, a stub stage/handler pair, and shared bronze/silver S3 key-layout helpers.
- Local MinIO + Lambda Runtime Interface Emulator scaffold (`docker-compose.yml`, `docker/lambda.Dockerfile`) mirroring the intended S3 key layout, with conventions documented in `docs/local-dev.md`.
- `src/capitol_lake/stages/bronze_write.py`: chamber-agnostic bronze contract — a pure, hash-gated idempotent write decision (no-op on matching sha256, versioned `<doc_id>.<sha256[:8]>.<ext>` key on a different hash, original key never overwritten) plus the sidecar `.meta.json` payload; `bronze_versioned_key`/`bronze_meta_key` key helpers.

### Changed

- Project configured from the harness template: name, code standards, agent skills docs.
