# House and Senate have two separate trigger mechanisms into the same
# downstream chain (#18's resolution): House keeps an EventBridge schedule
# end-to-end; Senate's manual `senate_collect` path has no schedule (its eFD
# search UI is Akamai-blocked from cloud egress, #17/#23) and instead relies
# on an S3-event notification forwarding onto extract's own SQS queue
# (ADR-0015 — not a direct Lambda invoke, so a Senate-triggered extract gets
# the same retry/DLQ handling House's own SQS-chained messages already do),
# fired for both a human's manual bronze upload and
# `senate_collect/handler.py`'s own writes. #67/#69 resolved the Akamai
# block for a real Chromium session, so `senate-collect-automated` gets its
# own EventBridge schedule below, mirroring House's — it still has no SQS
# trigger of its own, since that same S3-event notification (already scoped
# to `bronze/senate/*.html`) fires for its writes too, regardless of which
# Senate path produced them.

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

# --- Senate: bronze bucket S3 event -> extract's own SQS queue, no schedule
# (ADR-0015: forwarded onto the queue rather than invoking extract's Lambda
# directly, so a Senate-triggered failure gets the same retry/DLQ handling
# House's own SQS-chained messages already get) ---

data "aws_iam_policy_document" "allow_s3_send_to_extract_queue" {
  statement {
    sid       = "AllowS3SendToExtractQueue"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [var.extract_queue_arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [var.bronze_bucket_arn]
    }
  }
}

resource "aws_sqs_queue_policy" "allow_s3_extract_queue" {
  queue_url = var.extract_queue_url
  policy    = data.aws_iam_policy_document.allow_s3_send_to_extract_queue.json
}

resource "aws_s3_bucket_notification" "bronze" {
  bucket = var.bronze_bucket_id

  queue {
    queue_arn     = var.extract_queue_arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = var.senate_bronze_prefix
    filter_suffix = var.senate_bronze_suffix
  }

  depends_on = [aws_sqs_queue_policy.allow_s3_extract_queue]
}
