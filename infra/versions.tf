terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # S3-native locking (ADR-0009): no DynamoDB table. `bucket`/`region` are
  # supplied at `terraform init -backend-config=backend.hcl` time (see
  # backend.hcl.example) rather than hardcoded here, since they come out of
  # `infra/bootstrap`'s output and this file has no per-environment values.
  backend "s3" {
    key          = "capitol-lake/terraform.tfstate"
    use_lockfile = true
  }
}
