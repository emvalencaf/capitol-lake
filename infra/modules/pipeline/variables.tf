variable "bronze_bucket_name" {
  type = string
}

variable "bronze_bucket_arn" {
  type = string
}

variable "silver_bucket_name" {
  type = string
}

variable "silver_bucket_arn" {
  type = string
}

variable "ecr_repo_prefix" {
  description = "Prefix for each stage's ECR repository name."
  type        = string
  default     = "capitol-lake"
}

variable "llm_fallback_provider" {
  description = "LLM_FALLBACK_PROVIDER for the extract Lambda (src/capitol_lake/llm_providers.py: lm_studio, gemini or groq)."
  type        = string
  default     = "lm_studio"
}

variable "tags" {
  description = "Tags merged onto every resource this module creates (common_tags from the root module, per ADR-0009)."
  type        = map(string)
  default     = {}
}
