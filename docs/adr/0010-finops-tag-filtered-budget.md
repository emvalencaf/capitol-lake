# FinOps: tag-filtered AWS Budget with dedicated SNS alerts

The AWS account hosting capitol-lake is shared with other workloads, so an
account-wide Budget would conflate their spend with the project's near-zero
target. We scope a single AWS Budget to the cost allocation tag
`Project=capitol-lake`, alerting at 50%/80%/100% of a $5/month budget on
actual spend plus a forecasted->100% alert, via a dedicated SNS topic
(`capitol-lake-budget-alerts`) with an email subscription. All
Terraform-managed resources get `Project`, `Environment`, `Chamber`,
`Stage` and `ManagedBy` tags through provider-level `default_tags`, with
per-resource overrides for `Chamber`/`Stage` where they vary (e.g. each
`lambda-stage` module instance from ADR 0009). Both the Budget and the tag
scheme live in a new `infra/modules/finops` module, alongside
`storage`/`pipeline`/`lambda-stage`/`scheduling`; the root module still owns
the `common_tags` variable (ADR 0009) and passes it in.

## Considered options

- **Account-wide Budget**: rejected — the account isn't dedicated to
  capitol-lake, so it would alarm on unrelated spend and hide the
  project's own trend.
- **Tag-filtered Budget** (chosen): isolates the project's spend regardless
  of what else runs in the account.

## Consequences

User-defined cost allocation tags must be activated in the AWS Billing
Console (or via the Cost Explorer API) before the tag-filtered Budget can
actually see tagged spend — there's no Terraform resource for this, and
activation can take up to 24h to propagate. This is tracked as a separate
one-time Task ticket rather than folded into the Terraform module, since
it's manual work that gates the filter working, not a design decision.
