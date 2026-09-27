# Composes the three Lambdas the pipeline actually has (ADR-0011: house-collect,
# senate-collect and extract — extract also carries ticker/LLM-fallback and
# silver-write, see handlers/extract_handler.py's module docstring) from
# per-stage ECR repositories, IAM roles/policies and the `lambda-stage`
# module (ADR-0009), plus the SSM Parameter Store secrets #14's LLM fallback
# and #15's ticker resolution need (ADR-0009: SSM SecureString, not Secrets
# Manager — no free tier there).
#
# House and Senate collectors aren't SQS-triggered themselves (House is
# EventBridge-scheduled, Senate is invoked manually or off the bronze
# bucket's S3 event — both wired in `infra/modules/scheduling`); only
# `extract` consumes from its own queue, which `house_collect/handler.py`
# and a human's Senate upload both feed (house sends an SQS message
# directly; Senate's S3 event notification forwards onto that same queue
# rather than invoking extract directly, ADR-0015, giving it the same
# retry/DLQ handling — see #18's resolution).

locals {
  stage_names = ["house-collect", "senate-collect", "senate-collect-automated", "extract"]

  # Chamber override per stage (ADR-0010): only house-collect/senate-collect
  # are chamber-specific; extract processes both, so it keeps var.tags'
  # Chamber default ("n/a") rather than picking one.
  stage_chamber = {
    "house-collect"            = "house"
    "senate-collect"           = "senate"
    "senate-collect-automated" = "senate"
  }

  # Per-stage tags: var.tags + Stage, with the Chamber override above where
  # one applies. Shared by every per-stage resource below.
  stage_tags = {
    for stage in local.stage_names :
    stage => merge(
      var.tags,
      { Stage = stage },
      contains(keys(local.stage_chamber), stage) ? { Chamber = local.stage_chamber[stage] } : {}
    )
  }
}

resource "aws_ecr_repository" "this" {
  for_each = toset(local.stage_names)

  name                 = "${var.ecr_repo_prefix}-${each.value}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.stage_tags[each.value]
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

resource "aws_iam_role" "this" {
  for_each = toset(local.stage_names)

  name               = "capitol-lake-${each.value}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = local.stage_tags[each.value]
}

resource "aws_iam_role_policy_attachment" "logs" {
  for_each = toset(local.stage_names)

  role       = aws_iam_role.this[each.value].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- S3 access, scoped per stage's actual read/write shape ---

data "aws_iam_policy_document" "collect_s3" {
  for_each = toset(["house-collect", "senate-collect", "senate-collect-automated"])

  statement {
    sid       = "BronzeReadWrite"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${var.bronze_bucket_arn}/*"]
  }

  # Each collector's idempotent-skip check (read_existing_sha256) GetObjects
  # a meta key that legitimately doesn't exist yet on a filing's first run.
  # Without s3:ListBucket on the bucket itself, S3 can't tell the caller
  # apart from someone probing for the key's existence, so it returns 403
  # AccessDenied instead of 404 NoSuchKey — this statement is what lets a
  # missing key actually come back as "not found".
  statement {
    sid       = "BronzeList"
    actions   = ["s3:ListBucket"]
    resources = [var.bronze_bucket_arn]
  }
}

data "aws_iam_policy_document" "extract_s3" {
  statement {
    sid       = "BronzeRead"
    actions   = ["s3:GetObject"]
    resources = ["${var.bronze_bucket_arn}/*"]
  }

  statement {
    sid       = "SilverWrite"
    actions   = ["s3:PutObject"]
    resources = ["${var.silver_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "collect_s3" {
  for_each = toset(["house-collect", "senate-collect", "senate-collect-automated"])

  name   = "s3-access"
  role   = aws_iam_role.this[each.value].id
  policy = data.aws_iam_policy_document.collect_s3[each.value].json
}

resource "aws_iam_role_policy" "extract_s3" {
  name   = "s3-access"
  role   = aws_iam_role.this["extract"].id
  policy = data.aws_iam_policy_document.extract_s3.json
}

# --- Secrets (#14 LLM fallback, #15 ticker resolution): SSM SecureString,
# empty at apply time, a human populates the real value afterward. Only
# `extract` reads them (it's the Lambda that performs ticker resolution and
# LLM fallback, ADR-0011). Terraform provisions the parameter and IAM read
# access; wiring extract_handler.py to actually fetch these at runtime
# instead of a plain env var is a follow-up (it currently reads
# OPENFIGI_API_KEY/GEMINI_API_KEY/GROQ_API_KEY straight from the
# environment) — out of scope for this infra-only ticket (#44).

resource "aws_ssm_parameter" "secret" {
  for_each = toset(["openfigi-api-key", "gemini-api-key", "groq-api-key"])

  name  = "/capitol-lake/${each.value}"
  type  = "SecureString"
  value = "placeholder-set-after-apply"
  tags  = var.tags

  lifecycle {
    ignore_changes = [value]
  }
}

data "aws_iam_policy_document" "extract_secrets" {
  statement {
    sid       = "ReadLLMAndTickerSecrets"
    actions   = ["ssm:GetParameter"]
    resources = [for p in aws_ssm_parameter.secret : p.arn]
  }
}

resource "aws_iam_role_policy" "extract_secrets" {
  name   = "ssm-secrets-access"
  role   = aws_iam_role.this["extract"].id
  policy = data.aws_iam_policy_document.extract_secrets.json
}

# --- Lambda stages ---

module "extract" {
  source = "../lambda-stage"

  name      = "extract"
  image_uri = "${aws_ecr_repository.this["extract"].repository_url}:latest"
  role_arn  = aws_iam_role.this["extract"].arn

  handler_timeout_seconds        = 120
  memory_mb                      = 1024
  reserved_concurrent_executions = var.stage_reserved_concurrency

  # Slower retry backoff, not more retries: extract's failures here are
  # external rate-limiting (OpenFIGI/EDGAR/LLM provider), not bugs
  # (ADR-0011, #43).
  queue_visibility_timeout_seconds = 300

  environment_variables = {
    BRONZE_BUCKET              = var.bronze_bucket_name
    SILVER_BUCKET              = var.silver_bucket_name
    LLM_FALLBACK_PROVIDER      = var.llm_fallback_provider
    OPENFIGI_API_KEY_SSM_PARAM = aws_ssm_parameter.secret["openfigi-api-key"].name
    GEMINI_API_KEY_SSM_PARAM   = aws_ssm_parameter.secret["gemini-api-key"].name
    GROQ_API_KEY_SSM_PARAM     = aws_ssm_parameter.secret["groq-api-key"].name
  }

  tags = local.stage_tags["extract"]
}

resource "aws_iam_role_policy" "extract_sqs" {
  name = "sqs-consume-own-queue"
  role = aws_iam_role.this["extract"].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ConsumeExtractQueue"
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = module.extract.queue_arn
    }]
  })
}

module "house_collect" {
  source = "../lambda-stage"

  name        = "house-collect"
  image_uri   = "${aws_ecr_repository.this["house-collect"].repository_url}:latest"
  role_arn    = aws_iam_role.this["house-collect"].arn
  sqs_trigger = false # EventBridge-scheduled, not SQS-triggered (infra/modules/scheduling)

  # The lambda-stage default (60s) times out mid-run on a full-year backfill
  # (~500 filings/year, docs/cost.md, at roughly 1/s): a first invocation
  # against a filing year with a large backlog needs far more headroom than
  # the day-to-day trickle of new filings the daily schedule normally sees.
  # 900s matches Lambda's ceiling (and senate-collect-automated's own
  # timeout below) rather than guessing a number in between.
  handler_timeout_seconds        = 900
  reserved_concurrent_executions = var.stage_reserved_concurrency

  environment_variables = {
    BRONZE_BUCKET     = var.bronze_bucket_name
    EXTRACT_QUEUE_URL = module.extract.queue_url
  }

  tags = local.stage_tags["house-collect"]
}

resource "aws_iam_role_policy" "house_collect_sqs" {
  name = "sqs-send-to-extract"
  role = aws_iam_role.this["house-collect"].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "SendToExtractQueue"
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = module.extract.queue_arn
    }]
  })
}

module "senate_collect" {
  source = "../lambda-stage"

  name        = "senate-collect"
  image_uri   = "${aws_ecr_repository.this["senate-collect"].repository_url}:latest"
  role_arn    = aws_iam_role.this["senate-collect"].arn
  sqs_trigger = false # manual/local invocation only (#18); no schedule, no queue

  reserved_concurrent_executions = var.stage_reserved_concurrency

  environment_variables = {
    BRONZE_BUCKET = var.bronze_bucket_name
  }

  tags = local.stage_tags["senate-collect"]
}

module "senate_collect_automated" {
  source = "../lambda-stage"

  name        = "senate-collect-automated"
  image_uri   = "${aws_ecr_repository.this["senate-collect-automated"].repository_url}:latest"
  role_arn    = aws_iam_role.this["senate-collect-automated"].arn
  sqs_trigger = false # EventBridge-scheduled (infra/modules/scheduling); the bronze S3 event already chains into extract regardless of which Senate path wrote the object (#69)

  # Sized for a real Chromium session driving #67's eFD search-and-fetch
  # flow, not the stdlib-only stages above: 2048MB, and a timeout at
  # Lambda's ceiling since a worst-case full run (~300 filings at ~1 req/s)
  # approaches 900s, though most days finish well under (#69).
  memory_mb                      = 2048
  handler_timeout_seconds        = 900
  reserved_concurrent_executions = var.stage_reserved_concurrency

  environment_variables = {
    BRONZE_BUCKET = var.bronze_bucket_name
  }

  tags = local.stage_tags["senate-collect-automated"]
}
