# One pipeline stage: Lambda (container image) + its own SQS queue + DLQ,
# per the orchestration shape settled in #18/#43. Instantiated once per
# stage by the root module (collect, extract — which also carries ticker/
# LLM-fallback and silver-write, see handlers/extract_handler.py's module
# docstring for why those didn't end up as separate Lambdas), each with its
# own DLQ and IAM role (ADR-0009).

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-dlq"
  message_retention_seconds = 1209600 # 14 days (SQS max): give a human time to inspect a dead-lettered message.
  tags                      = var.tags
}

resource "aws_sqs_queue" "queue" {
  count                      = var.sqs_trigger ? 1 : 0
  name                       = "${var.name}-queue"
  visibility_timeout_seconds = var.queue_visibility_timeout_seconds
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
  tags = var.tags
}

resource "aws_lambda_function" "this" {
  function_name = "capitol-lake-${var.name}"
  role          = var.role_arn
  package_type  = "Image"
  image_uri     = var.image_uri
  timeout       = var.handler_timeout_seconds
  memory_size   = var.memory_mb

  reserved_concurrent_executions = var.reserved_concurrent_executions

  environment {
    variables = var.environment_variables
  }

  tags = var.tags
}

resource "aws_lambda_event_source_mapping" "sqs" {
  count            = var.sqs_trigger ? 1 : 0
  event_source_arn = aws_sqs_queue.queue[0].arn
  function_name    = aws_lambda_function.this.arn
  batch_size       = var.batch_size

  function_response_types = ["ReportBatchItemFailures"]
}
