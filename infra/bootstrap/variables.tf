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
  description = "Tags applied to the state bucket."
  type        = map(string)
  default = {
    Project   = "capitol-lake"
    ManagedBy = "terraform"
  }
}
