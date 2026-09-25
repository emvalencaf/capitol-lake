variable "name" {
  description = "Stage name, used to derive resource names (e.g. \"extract\", \"house-collect\")."
  type        = string
}

variable "image_uri" {
  description = "ECR image URI this stage's Lambda runs (built from the matching docker/*.Dockerfile)."
  type        = string
}

variable "handler_timeout_seconds" {
  description = "Lambda function timeout, in seconds."
  type        = number
  default     = 60
}

variable "memory_mb" {
  description = "Lambda function memory, in MB."
  type        = number
  default     = 512
}

variable "reserved_concurrent_executions" {
  description = <<-EOT
    Reserved concurrency for this stage's Lambda (#43: capped low, 5-10, to
    stay polite to downstream free-tier APIs and isolate per-filing
    failures). `-1` (Terraform's "unset" sentinel) leaves it unreserved.
  EOT
  type        = number
  default     = 5
}

variable "queue_visibility_timeout_seconds" {
  description = <<-EOT
    SQS queue visibility timeout. Doubles as this stage's retry backoff: a
    failed message becomes visible for redelivery only after this many
    seconds, so a longer value here means a slower retry cadence without
    changing `max_receive_count`. The ticker/LLM-fallback stage (#43: this
    repo's `extract` Lambda also performs ticker resolution and LLM
    fallback, see handlers/extract_handler.py's module docstring) sets this
    higher than the default, since its failures are external
    rate-limiting, not bugs, and a fast retry would just burn free-tier
    quota faster.
  EOT
  type        = number
  default     = 60
}

variable "max_receive_count" {
  description = "SQS redrive policy: how many deliveries before a message moves to the DLQ. Uniform across every stage (#43) regardless of that stage's backoff."
  type        = number
  default     = 3
}

variable "sqs_trigger" {
  description = "Whether this stage has an SQS event source mapping (false for a stage triggered only by EventBridge or S3 events, e.g. house-collect)."
  type        = bool
  default     = true
}

variable "batch_size" {
  description = "SQS event source mapping batch size. #43: one filing per invocation."
  type        = number
  default     = 1
}

variable "environment_variables" {
  description = "Extra environment variables for this stage's Lambda function."
  type        = map(string)
  default     = {}
}

variable "role_arn" {
  description = "IAM role ARN this stage's Lambda assumes (created per stage, per ADR-0009)."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource this module creates (FinOps cost-allocation tag, per ADR-0010, comes in via the caller's common_tags)."
  type        = map(string)
  default     = {}
}
