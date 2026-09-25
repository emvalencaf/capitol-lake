output "bronze_bucket_id" {
  value = aws_s3_bucket.bronze.id
}

output "bronze_bucket_name" {
  value = aws_s3_bucket.bronze.bucket
}

output "bronze_bucket_arn" {
  value = aws_s3_bucket.bronze.arn
}

output "silver_bucket_id" {
  value = aws_s3_bucket.silver.id
}

output "silver_bucket_name" {
  value = aws_s3_bucket.silver.bucket
}

output "silver_bucket_arn" {
  value = aws_s3_bucket.silver.arn
}
