# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Entries are added
under `Unreleased` in the PR that makes the change, and moved under a dated
heading when `development` is released to `master`.

## [Unreleased]

### Added

- `src/capitol_lake/schema.py`: silver-layer `Filing` and `Transaction` models — canonical `Owner`/`TransactionType` enums with raw-text fields, `(min, max)` `ValueRange`, an invariant-enforced `disclosure_lag`, a `ticker` slot for future resolution, and row-level `confidence`/`Provenance`.
- ADR 0010: FinOps decision — AWS Budget filtered by the `Project=capitol-lake` cost allocation tag, alert thresholds, and Terraform tagging scheme.
- `src/capitol_lake/` skeleton with the pure-function-plus-handler stage convention, a stub stage/handler pair, and shared bronze/silver S3 key-layout helpers.
- Local MinIO + Lambda Runtime Interface Emulator scaffold (`docker-compose.yml`, `docker/lambda.Dockerfile`) mirroring the intended S3 key layout, with conventions documented in `docs/local-dev.md`.

### Changed

- Project configured from the harness template: name, code standards, agent skills docs.
