output "house_schedule_rule_arn" {
  value = aws_cloudwatch_event_rule.house_schedule.arn
}

output "senate_automated_schedule_rule_arn" {
  value = aws_cloudwatch_event_rule.senate_automated_schedule.arn
}
