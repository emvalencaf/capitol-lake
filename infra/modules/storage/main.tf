# Single project S3 bucket (#6/#9/#19's key layout, lifted to AWS per #18).
# Bronze and silver are key prefixes inside it (bronze/..., silver/...,
# shared/keys.py), not separate buckets — one bucket is enough since access
# is already scoped by prefix in modules/pipeline's IAM policies.
# No lifecycle rules: both layers are meant to be kept indefinitely (bronze
# is the immutable source-of-record, silver is small Parquet, ADR-0008).

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_prefix
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
