variable "bucket_prefix" {
  description = "Prefix for the bronze/silver bucket names (must be globally unique in S3)."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource this module creates (common_tags from the root module, per ADR-0009)."
  type        = map(string)
  default     = {}
}
