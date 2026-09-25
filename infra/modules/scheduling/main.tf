# House and Senate have two separate trigger mechanisms into the same
# downstream chain (#18's resolution): House keeps an EventBridge schedule
# end-to-end; Senate has no schedule (its eFD search UI is Akamai-blocked
# from cloud egress, #17/#23) and instead wires an S3-event trigger straight
# into `extract`, fired for both a human's manual bronze upload and
# `senate_collect_handler`'s own writes — the entry point doesn't matter,
# only that a Senate bronze object landed.

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

# --- Senate: bronze bucket S3 event -> extract, no schedule ---

resource "aws_lambda_permission" "allow_s3_extract" {
  statement_id  = "AllowS3InvokeExtract"
  action        = "lambda:InvokeFunction"
  function_name = var.extract_function_name
  principal     = "s3.amazonaws.com"
  source_arn    = var.bronze_bucket_arn
}

resource "aws_s3_bucket_notification" "bronze" {
  bucket = var.bronze_bucket_id

  lambda_function {
    lambda_function_arn = var.extract_function_arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = var.senate_bronze_prefix
    filter_suffix       = var.senate_bronze_suffix
  }

  depends_on = [aws_lambda_permission.allow_s3_extract]
}
