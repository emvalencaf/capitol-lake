variable "aws_region" {
  description = "AWS region the state bucket is created in."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = <<-EOT
    Name of the S3 bucket that holds the main stack's Terraform state
    (S3-native locking, ADR-0009 — no DynamoDB table). Must be globally
    unique; override if the default is already taken.
  EOT
  type        = string
  default     = "capitol-lake-terraform-state"
}

variable "tags" {
  description = "Tags applied to the state bucket and the GitHub Actions OIDC resources."
  type        = map(string)
  default = {
    Project   = "capitol-lake"
    ManagedBy = "terraform"
  }
}

variable "github_repository" {
  description = "GitHub repository the OIDC trust policy scopes to, as \"owner/repo\" (#46)."
  type        = string
  default     = "emvalencaf/capitol-lake"
}

variable "github_environment" {
  description = <<-EOT
    Name of the GitHub Environment the `terraform apply` job runs through
    (required-reviewer protection configured by hand in repo settings, #46).
    Must match the `environment:` key in .github/workflows/infra-cicd.yml.
  EOT
  type        = string
  default     = "production"
}
