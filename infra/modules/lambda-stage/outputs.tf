output "function_arn" {
  value = aws_lambda_function.this.arn
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "queue_url" {
  description = "This stage's SQS queue URL, for an upstream stage to enqueue into. `null` when `sqs_trigger = false`."
  value       = var.sqs_trigger ? aws_sqs_queue.queue[0].url : null
}

output "queue_arn" {
  description = "This stage's SQS queue ARN, for an upstream stage's IAM policy to grant `sqs:SendMessage` on. `null` when `sqs_trigger = false`."
  value       = var.sqs_trigger ? aws_sqs_queue.queue[0].arn : null
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}
