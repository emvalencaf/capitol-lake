output "bronze_bucket_name" {
  value = module.storage.bronze_bucket_name
}

output "silver_bucket_name" {
  value = module.storage.silver_bucket_name
}

output "ecr_repository_urls" {
  description = "Map of stage name to its ECR repository URL, for building/pushing each stage's container image."
  value       = module.pipeline.ecr_repository_urls
}

output "extract_queue_url" {
  value = module.pipeline.extract_queue_url
}

output "house_collect_function_name" {
  value = module.pipeline.house_collect_function_name
}

output "senate_collect_function_name" {
  value = module.pipeline.senate_collect_function_name
}

output "extract_function_name" {
  value = module.pipeline.extract_function_name
}

output "finops_alerts_topic_arn" {
  description = "SNS topic budget alerts and the pipeline staleness alarm publish to."
  value       = module.finops.alerts_topic_arn
}
