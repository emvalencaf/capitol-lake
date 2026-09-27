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

variable "tags" {
  description = "Tags merged onto every resource this module creates (common_tags from the root module, per ADR-0009)."
  type        = map(string)
  default     = {}
}
