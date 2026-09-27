variable "budget_amount_usd" {
  description = "Monthly AWS Budget limit, in USD, for spend tagged Project=capitol-lake."
  type        = string
  default     = "5"
}

variable "alert_email" {
  description = "Email address subscribed to both the budget alerts and the staleness alarm's SNS topic."
  type        = string
}

variable "staleness_function_name" {
  description = "Name of the Lambda function whose Invocations metric the dead-man's-switch alarm watches (the scheduled entry point, e.g. house-collect)."
  type        = string
}

variable "staleness_period_seconds" {
  description = <<-EOT
    Length, in seconds, of one scheduled run interval for `staleness_function_name`
    (must match its EventBridge schedule, e.g. 86400 for rate(1 day)). The alarm
    evaluates 2 consecutive periods of this length with zero invocations, i.e.
    fires after 2x the scheduled interval with no successful run.
  EOT
  type        = number
}

variable "senate_automated_function_name" {
  description = "Name of the senate-collect-automated Lambda function the dedicated Errors alarm watches (#69)."
  type        = string
}

variable "senate_automated_error_period_seconds" {
  description = <<-EOT
    CloudWatch period, in seconds, the senate-collect-automated Errors alarm
    evaluates. Kept short (unlike staleness_period_seconds) so a single
    failed run alerts promptly rather than waiting out a full schedule
    interval.
  EOT
  type        = number
  default     = 300
}

variable "tags" {
  description = <<-EOT
    Tags merged onto every resource this module creates (common_tags from the
    root module, per ADR-0009). Must include a "Project" key — the Budget's
    cost filter reads it directly so the filtered tag value can't drift from
    what every other resource is actually tagged with.
  EOT
  type        = map(string)
  default     = {}
}
