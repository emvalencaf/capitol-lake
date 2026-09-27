variable "house_collect_function_name" {
  type = string
}

variable "house_collect_function_arn" {
  type = string
}

variable "house_filing_year" {
  description = "Year passed as the scheduled invocation's event input (collect_house's `event[\"year\"]`)."
  type        = number
}

variable "house_schedule_expression" {
  description = "EventBridge schedule expression (rate(...) or cron(...)) for the House collector."
  type        = string
  default     = "rate(1 day)"
}

variable "senate_collect_automated_function_name" {
  type = string
}

variable "senate_collect_automated_function_arn" {
  type = string
}

variable "senate_automated_schedule_expression" {
  description = "EventBridge schedule expression (rate(...) or cron(...)) for the automated Senate collector."
  type        = string
  default     = "rate(1 day)"
}

variable "extract_queue_arn" {
  description = "ARN of extract's own SQS queue (module.pipeline's extract_queue_arn output). The bronze bucket's S3 event notification forwards onto this queue instead of invoking extract's Lambda directly (ADR-0015), so a Senate-triggered extract gets the same retry/DLQ handling House's own SQS-chained messages already do."
  type        = string
}

variable "extract_queue_url" {
  description = "URL of extract's own SQS queue (module.pipeline's extract_queue_url output), required by aws_sqs_queue_policy's queue_url argument (the queue resource's ARN alone isn't accepted there)."
  type        = string
}

variable "bronze_bucket_id" {
  type = string
}

variable "bronze_bucket_arn" {
  type = string
}

variable "senate_bronze_prefix" {
  description = "Bronze key prefix an S3 event must match to trigger extract directly (house_collect_handler.py already chains its own writes via SQS, so this must stay scoped to Senate's chamber prefix to avoid double-processing)."
  type        = string
  default     = "bronze/senate/"
}

variable "senate_bronze_suffix" {
  description = "Bronze key suffix an S3 event must match — Senate bronze objects are always .html (senate_collect.py); excludes the .meta.json sidecar object bronze_write.py also writes."
  type        = string
  default     = ".html"
}

variable "tags" {
  description = "Tags merged onto every resource this module creates (common_tags from the root module, per ADR-0009)."
  type        = map(string)
  default     = {}
}
