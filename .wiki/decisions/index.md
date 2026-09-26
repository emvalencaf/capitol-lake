# Decisions

One concept per ADR under [`docs/adr/`](../../docs/adr/), summarizing its decision.

* [ADR 0001: Lambda packaged as a container image, not zip + layers](0001-lambda-container-image-packaging.md)
* [ADR 0002: Accept null transaction type, cap-gains and value-range for scanned filings, no zonal OCR](0002-scanned-filing-fields-null-not-zonal-ocr.md)
* [ADR 0003: Digital parser validates labels before accepting positional field values](0003-digital-parser-label-validated-positional-walk.md)
* [ADR 0008: Silver stays Parquet on S3, one part-<doc_id>.parquet per filing, no compaction](0008-silver-storage-stays-parquet-part-per-doc-id.md)
* [ADR 0009: Terraform module structure, state, and CI/CD for the cloud lift](0009-terraform-module-structure-and-cicd.md)
* [ADR 0010: FinOps -- tag-filtered AWS Budget with dedicated SNS alerts](0010-finops-tag-filtered-budget.md)
* [ADR 0011: Extract stage packaging (Debian base image) and actual Lambda count (three, not four)](0011-extract-stage-alt-base-image-and-lambda-count.md)
* [ADR 0012: Wiring the Terraform root stack -- bucket naming, SSM handoff, S3-event scoping, schedule input](0012-terraform-root-stack-wiring.md)
* [ADR 0013: Senate HTML extraction -- no doc-id cross-check, Exchange as one row with two legs](0013-senate-html-extraction-design.md)
