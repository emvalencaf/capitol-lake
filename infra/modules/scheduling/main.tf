# House and the automated Senate collector both get an EventBridge schedule
# below; the manual `senate_collect` path (its eFD search UI is
# Akamai-blocked from cloud egress, #17/#23) has none and is invoked by
# hand. All three collectors now enqueue their own bronze-to-extract SQS
# messages directly from their handlers (ADR-0016), exactly like House
# always did — there is no S3-event bridge here any more (that was
# ADR-0015's fix, superseded once Senate's handlers could just send their
# own SQS messages instead of relying on infra to forward S3 events).

# --- House: EventBridge schedule -> house-collect ---

resource "aws_cloudwatch_event_rule" "house_schedule" {
  name                = "capitol-lake-house-collect-schedule"
  description         = "Triggers the House collector Lambda on a schedule (ADR-0009, #18)."
  schedule_expression = var.house_schedule_expression
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "house_collect" {
  rule = aws_cloudwatch_event_rule.house_schedule.name
  arn  = var.house_collect_function_arn

  input = jsonencode({ year = var.house_filing_year })
}

resource "aws_lambda_permission" "allow_eventbridge_house_collect" {
  statement_id  = "AllowEventBridgeInvokeHouseCollect"
  action        = "lambda:InvokeFunction"
  function_name = var.house_collect_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.house_schedule.arn
}

# --- Senate automated: EventBridge schedule -> senate-collect-automated ---

resource "aws_cloudwatch_event_rule" "senate_automated_schedule" {
  name                = "capitol-lake-senate-collect-automated-schedule"
  description         = "Triggers the automated Senate collector Lambda on a schedule (#69)."
  schedule_expression = var.senate_automated_schedule_expression
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "senate_collect_automated" {
  rule = aws_cloudwatch_event_rule.senate_automated_schedule.name
  arn  = var.senate_collect_automated_function_arn
}

resource "aws_lambda_permission" "allow_eventbridge_senate_collect_automated" {
  statement_id  = "AllowEventBridgeInvokeSenateCollectAutomated"
  action        = "lambda:InvokeFunction"
  function_name = var.senate_collect_automated_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.senate_automated_schedule.arn
}
