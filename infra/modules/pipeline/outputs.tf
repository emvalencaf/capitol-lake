output "house_collect_function_name" {
  value = module.house_collect.function_name
}

output "house_collect_function_arn" {
  value = module.house_collect.function_arn
}

output "senate_collect_function_name" {
  value = module.senate_collect.function_name
}

output "senate_collect_function_arn" {
  value = module.senate_collect.function_arn
}

output "senate_collect_automated_function_name" {
  value = module.senate_collect_automated.function_name
}

output "senate_collect_automated_function_arn" {
  value = module.senate_collect_automated.function_arn
}

output "extract_function_name" {
  value = module.extract.function_name
}

output "extract_function_arn" {
  value = module.extract.function_arn
}

output "extract_queue_url" {
  value = module.extract.queue_url
}

output "ecr_repository_urls" {
  description = "Map of stage name to its ECR repository URL, for building/pushing each stage's container image."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}
