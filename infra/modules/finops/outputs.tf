output "alerts_topic_arn" {
  description = "SNS topic ARN both the budget notifications and the staleness alarm publish to."
  value       = aws_sns_topic.budget_alerts.arn
}

output "budget_name" {
  value = aws_budgets_budget.capitol_lake.name
}

output "staleness_alarm_arn" {
  value = aws_cloudwatch_metric_alarm.staleness.arn
}
