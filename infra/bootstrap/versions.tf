terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Local state deliberately: this module provisions the bucket the main
  # stack's own S3 backend depends on, so it can't use that backend itself
  # (ADR-0009). Run by hand, once, before the main stack's first `init`.
}
