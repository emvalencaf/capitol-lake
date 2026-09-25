terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local state deliberately (same reasoning as infra/bootstrap): this is a
  # one-off, run-by-hand probe (#29), not part of the main stack's S3-backed
  # state or its CI/CD apply gate — see README.md.
}
