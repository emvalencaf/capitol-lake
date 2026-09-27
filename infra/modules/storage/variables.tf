variable "bucket_prefix" {
  description = "Name of the single project S3 bucket, holding bronze/silver as key prefixes (must be globally unique in S3)."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource this module creates (common_tags from the root module, per ADR-0009)."
  type        = map(string)
  default     = {}
}
