variable "aws_region" {
  description = "AWS region the probe Lambda is created in."
  type        = string
  default     = "us-east-1"
}

variable "image_uri" {
  description = <<-EOT
    ECR image URI for the probe, built from
    docker/senate_akamai_probe.Dockerfile and pushed to the repository this
    module creates (`terraform output ecr_repository_url`, then the usual
    `docker build` / `aws ecr get-login-password` / `docker push` steps —
    no image is built or pushed by Terraform itself).
  EOT
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource this module creates."
  type        = map(string)
  default = {
    Project = "capitol-lake"
    Purpose = "senate-akamai-probe-29"
  }
}
