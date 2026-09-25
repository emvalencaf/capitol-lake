# Standalone, run-by-hand probe stack for #29: one Lambda, no SQS/DLQ (no
# pipeline to chain into — this never touches bronze/silver), answering
# whether a Lambda-origin headless-Playwright request clears the Senate eFD
# Akamai check. Deliberately outside `infra/`'s main root module and its
# CI/CD apply gate (`.github/workflows/infra-cicd.yml` is path-filtered to
# `infra/**`, which *does* include this directory — if that ever becomes a
# problem, scope the workflow's path filter to exclude `infra/probes/**`,
# or move this module out of `infra/` entirely): this exists to answer one
# question once, not to run continuously, so it doesn't belong in the
# always-applied stack. See README.md for the full run-once/tear-down
# procedure.

provider "aws" {
  region = var.aws_region
}

resource "aws_ecr_repository" "probe" {
  name                 = "capitol-lake-senate-akamai-probe"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = var.tags
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "probe" {
  name               = "capitol-lake-senate-akamai-probe-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = var.tags
}

# CloudWatch Logs only — this probe never touches S3/SQS, its result is the
# raw invoke response a human reads and pastes into the research doc.
resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.probe.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

module "lambda" {
  source = "../../modules/lambda-stage"

  name        = "senate-akamai-probe"
  image_uri   = var.image_uri
  role_arn    = aws_iam_role.probe.arn
  sqs_trigger = false

  # Playwright's Chromium cold start plus a live page load is slower and
  # heavier than any real pipeline stage's Lambda.
  handler_timeout_seconds = 120
  memory_mb               = 1024

  tags = var.tags
}
