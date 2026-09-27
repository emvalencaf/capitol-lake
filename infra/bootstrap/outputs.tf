output "state_bucket_name" {
  description = "Feed this into `infra/backend.hcl`'s `bucket` for the main stack's `terraform init -backend-config=backend.hcl`."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_arn" {
  value = aws_s3_bucket.state.arn
}

output "github_actions_role_arn" {
  description = "Feed this into the repo's AWS_ROLE_ARN Actions secret (#46) — the ARN itself grants no access without the OIDC trust condition, but it's kept as a secret so Actions logs mask it."
  value       = aws_iam_role.github_actions_terraform.arn
}
