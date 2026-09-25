# Bronze/silver S3 buckets (#6/#9/#19's key layout, lifted to AWS per #18).
# No lifecycle rules: both layers are meant to be kept indefinitely (bronze
# is the immutable source-of-record, silver is small Parquet, ADR-0008).

resource "aws_s3_bucket" "bronze" {
  bucket = "${var.bucket_prefix}-bronze"
  tags   = merge(var.tags, { Stage = "bronze" })
}

resource "aws_s3_bucket" "silver" {
  bucket = "${var.bucket_prefix}-silver"
  tags   = merge(var.tags, { Stage = "silver" })
}

resource "aws_s3_bucket_versioning" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "silver" {
  bucket = aws_s3_bucket.silver.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "silver" {
  bucket = aws_s3_bucket.silver.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "bronze" {
  bucket = aws_s3_bucket.bronze.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "silver" {
  bucket = aws_s3_bucket.silver.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
