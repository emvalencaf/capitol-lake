# FinOps: tag-filtered AWS Budget (ADR-0010) plus the pipeline's dead-man's-
# switch staleness alarm, both alerting through one dedicated SNS topic.

resource "aws_sns_topic" "budget_alerts" {
  name = "capitol-lake-budget-alerts"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "budget_alerts_email" {
  topic_arn = aws_sns_topic.budget_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Scoped to the Project cost allocation tag, not account-wide (ADR-0010):
# the account is shared with other workloads. Activating this as a user-
# defined cost allocation tag in the Billing Console is a separate, manual
# one-time step (ADR-0010's Consequences) — Terraform can't do it.
resource "aws_budgets_budget" "capitol_lake" {
  name         = "capitol-lake-monthly"
  budget_type  = "COST"
  limit_amount = var.budget_amount_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name = "TagKeyValue"
    # Reads the Project value straight off var.tags (common_tags from the
    # root module) rather than a separate variable, so there's one place
    # (ADR-0009) defining what "capitol-lake" spend means — this can't drift
    # out of sync with the tag every other resource actually carries.
    values = [format("user:Project$%s", var.tags["Project"])]
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator       = "GREATER_THAN"
      threshold                 = notification.value
      threshold_type            = "PERCENTAGE"
      notification_type         = "ACTUAL"
      subscriber_sns_topic_arns = [aws_sns_topic.budget_alerts.arn]
    }
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.budget_alerts.arn]
  }
}

# Dead-man's-switch: alarms if `staleness_function_name` completes zero
# successful invocations (Invocations - Errors) over 2 consecutive periods
# of `staleness_period_seconds`, i.e. no successful run within 2x the
# scheduled interval. `treat_missing_data = "breaching"` so a Lambda that
# never ran in the first place (or stopped being invoked entirely) alarms
# too, not just one that ran and failed.
resource "aws_cloudwatch_metric_alarm" "staleness" {
  alarm_name          = "capitol-lake-pipeline-staleness"
  alarm_description   = "No successful run of ${var.staleness_function_name} within 2x its scheduled interval."
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  evaluation_periods  = 2
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.budget_alerts.arn]
  ok_actions          = [aws_sns_topic.budget_alerts.arn]
  tags                = var.tags

  metric_query {
    id          = "successes"
    expression  = "invocations - errors"
    label       = "Successful invocations"
    return_data = true
  }

  metric_query {
    id = "invocations"

    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Invocations"
      period      = var.staleness_period_seconds
      stat        = "Sum"
      dimensions = {
        FunctionName = var.staleness_function_name
      }
    }
  }

  metric_query {
    id = "errors"

    metric {
      namespace   = "AWS/Lambda"
      metric_name = "Errors"
      period      = var.staleness_period_seconds
      stat        = "Sum"
      dimensions = {
        FunctionName = var.staleness_function_name
      }
    }
  }
}

# Dedicated to `senate-collect-automated` (#69), distinct from the House-only
# staleness alarm above: #67 raises on any non-"cleared" outcome, so a single
# blocked/failed run should alert the same day rather than wait out a
# multi-day zero-invocations window. `treat_missing_data = "notBreaching"`
# (unlike staleness) since a short period with zero invocations just means
# it isn't scheduled to run yet, not that it's stopped running.
resource "aws_cloudwatch_metric_alarm" "senate_automated_errors" {
  alarm_name          = "capitol-lake-senate-collect-automated-errors"
  alarm_description   = "${var.senate_automated_function_name} reported at least one Lambda error."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 1
  period              = var.senate_automated_error_period_seconds
  statistic           = "Sum"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions = {
    FunctionName = var.senate_automated_function_name
  }
  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.budget_alerts.arn]
  ok_actions         = [aws_sns_topic.budget_alerts.arn]
  tags               = var.tags
}
