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
    lambda-stage instance).
  EOT
  type        = map(string)
  default = {
    Project   = "capitol-lake"
    ManagedBy = "terraform"
  }
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
  description = "LLM_FALLBACK_PROVIDER for the extract Lambda (src/capitol_lake/llm_providers.py: lm_studio, gemini or groq)."
  type        = string
  default     = "lm_studio"
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
