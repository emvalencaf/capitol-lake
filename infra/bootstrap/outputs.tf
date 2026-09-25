output "state_bucket_name" {
  description = "Feed this into `infra/backend.hcl`'s `bucket` for the main stack's `terraform init -backend-config=backend.hcl`."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_arn" {
  value = aws_s3_bucket.state.arn
}
