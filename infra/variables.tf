variable "aws_region" {
  description = "AWS region the stack deploys into."
  type        = string
  default     = "us-east-1"
}

variable "common_tags" {
  description = <<-EOT
    Tags applied to every resource via the AWS provider's default_tags
    (ADR-0009: single place to define the tagging convention; per-resource
    Chamber/Stage overrides happen in the child modules, e.g. each
    lambda-stage instance). Chamber defaults to "n/a" here since most
    resources (storage, finops) aren't chamber-specific; house-collect and
    senate-collect override it per ADR-0010.
  EOT
  type        = map(string)
  default = {
    Project     = "capitol-lake"
    Environment = "production"
    Chamber     = "n/a"
    ManagedBy   = "terraform"
  }
}

variable "finops_alert_email" {
  description = "Email address subscribed to the FinOps SNS topic (budget alerts and pipeline staleness alarm, ADR-0010)."
  type        = string
}

variable "budget_amount_usd" {
  description = "Monthly AWS Budget limit, in USD, for spend tagged Project=capitol-lake (ADR-0010)."
  type        = string
  default     = "5"
}

variable "house_schedule_period_seconds" {
  description = <<-EOT
    Length, in seconds, of one House collector schedule interval — must match
    var.house_schedule_expression (86400 for the default rate(1 day)). Feeds
    the finops module's staleness alarm, which fires after 2 consecutive
    periods of this length with no successful house-collect run.
  EOT
  type        = number
  default     = 86400
}

variable "bucket_prefix" {
  description = "Prefix for the bronze/silver S3 bucket names (must be globally unique in S3)."
  type        = string
  default     = "capitol-lake"
}

variable "ecr_repo_prefix" {
  description = "Prefix for each pipeline stage's ECR repository name."
  type        = string
  default     = "capitol-lake"
}

variable "llm_fallback_provider" {
  description = "LLM_FALLBACK_PROVIDER for the extract Lambda (src/shared/llm_providers.py: lm_studio, gemini or groq)."
  type        = string
  default     = "lm_studio"
}

variable "stage_reserved_concurrency" {
  description = <<-EOT
    Reserved concurrency applied to each of the 4 pipeline stage Lambdas.
    `-1` (Terraform's "unset" sentinel, and the default here) leaves every
    stage unreserved, sharing the account's general concurrency pool.

    #43 originally reserved 5 per stage to stay polite to downstream
    free-tier APIs and isolate per-filing failures in production — a fresh
    AWS account's default Lambda concurrent-executions quota is often below
    the account-wide 10-unit unreserved floor AWS always keeps aside, though,
    which fails `terraform apply` on every stage with "decreases account's
    UnreservedConcurrentExecution below its minimum value of [10]" unless a
    Service Quotas increase is requested first. This project's scope is
    demonstrative rather than production traffic, so it defaults to
    unreserved instead; set this to `5` (or request the quota increase) if
    isolating stages from each other's concurrency becomes worth the
    trade-off.
  EOT
  type        = number
  default     = -1
}

variable "house_filing_year" {
  description = <<-EOT
    Year passed to the scheduled House collector's event input
    (`collect_house`'s `event["year"]`). Bumped by hand once a year — #44
    deliberately keeps the schedule target's input static rather than
    computing a rolling "current year" in Terraform, since House PTRs are
    indexed by filing year and a plan shouldn't drift just because time
    passed.
  EOT
  type        = number
  default     = 2026
}

variable "house_schedule_expression" {
  description = "EventBridge schedule expression for the House collector."
  type        = string
  default     = "rate(1 day)"
}

variable "senate_automated_schedule_expression" {
  description = "EventBridge schedule expression for the automated Senate collector (#69)."
  type        = string
  default     = "rate(1 day)"
}

variable "senate_automated_error_period_seconds" {
  description = <<-EOT
    CloudWatch period, in seconds, the senate-collect-automated Errors alarm
    evaluates (#69). Kept short by default (see
    modules/finops/variables.tf's senate_automated_error_period_seconds) so a
    single failed run alerts promptly rather than waiting out a full
    schedule interval.
  EOT
  type        = number
  default     = 300
}
