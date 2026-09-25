output "ecr_repository_url" {
  description = "Push the image built from docker/senate_akamai_probe.Dockerfile here before the first apply."
  value       = aws_ecr_repository.probe.repository_url
}

output "function_name" {
  description = "Feed into `aws lambda invoke --function-name`."
  value       = module.lambda.function_name
}
