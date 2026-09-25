# GitHub Actions OIDC (ADR-0009, #46): no long-lived AWS access keys as repo
# secrets. GitHub's OIDC provider is trusted by one IAM role, assumed
# per-workflow-run via `aws-actions/configure-aws-credentials`. Bootstrapped
# by hand alongside the state bucket (this module's own state stays local,
# per versions.tf) since the CI workflow needs the role to exist before its
# first `terraform init` against the main stack can run.
#
# One role serves both jobs; the trust policy's `sub` condition is what
# separates them:
# - `plan` runs on pull requests touching `infra/**`, no environment gate —
#   GitHub sets `sub = repo:<repo>:pull_request` for those.
# - `apply` runs on push to `master` through the `var.github_environment`
#   GitHub Environment (required-reviewer protection, configured by hand in
#   repo settings — Terraform's `github` provider could manage this but
#   isn't part of this stack, same reasoning as the Billing Console
#   cost-allocation tag step in ../README.md) — GitHub sets
#   `sub = repo:<repo>:environment:<name>` for those.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]

  tags = var.tags
}

data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:pull_request",
        "repo:${var.github_repository}:environment:${var.github_environment}",
      ]
    }
  }
}

resource "aws_iam_role" "github_actions_terraform" {
  name               = "capitol-lake-github-actions-terraform"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json
  tags               = var.tags
}

# Scoped to the resource types and naming conventions the main stack
# (infra/main.tf and its child modules) actually creates, not
# AdministratorAccess/PowerUserAccess — the AWS account is shared with other
# workloads (ADR-0010's Consequences) and this repo goes public in Phase 3
# (ADR-0009). Resource names that already carry a `capitol-lake` prefix are
# scoped by that prefix; the pipeline module's per-stage SQS queues,
# EventBridge rule, SNS topic, budget and CloudWatch alarm don't, so those
# are scoped by their own fixed/known names instead.
data "aws_iam_policy_document" "github_actions_terraform" {
  statement {
    sid = "TerraformStateBucket"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]
  }

  statement {
    sid = "AppBuckets"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetBucketTagging",
      "s3:PutBucketTagging",
      "s3:GetBucketVersioning",
      "s3:PutBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:PutEncryptionConfiguration",
      "s3:GetBucketPublicAccessBlock",
      "s3:PutBucketPublicAccessBlock",
      "s3:GetBucketPolicy",
      "s3:PutBucketPolicy",
      "s3:GetBucketNotification",
      "s3:PutBucketNotification",
      "s3:GetBucketLocation",
    ]
    resources = [
      "arn:aws:s3:::capitol-lake-*",
      "arn:aws:s3:::capitol-lake-*/*",
    ]
  }

  statement {
    sid = "EcrRepositories"
    actions = [
      "ecr:CreateRepository",
      "ecr:DeleteRepository",
      "ecr:DescribeRepositories",
      "ecr:GetRepositoryPolicy",
      "ecr:SetRepositoryPolicy",
      "ecr:PutImageScanningConfiguration",
      "ecr:ListTagsForResource",
      "ecr:TagResource",
      "ecr:UntagResource",
    ]
    resources = ["arn:aws:ecr:*:*:repository/capitol-lake-*"]
  }

  statement {
    sid = "LambdaRoles"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:PassRole",
    ]
    resources = ["arn:aws:iam::*:role/capitol-lake-*"]
  }

  statement {
    sid = "LambdaFunctions"
    actions = [
      "lambda:CreateFunction",
      "lambda:DeleteFunction",
      "lambda:GetFunction",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
      "lambda:PutFunctionConcurrency",
      "lambda:DeleteFunctionConcurrencyConfig",
      "lambda:GetFunctionConcurrency",
      "lambda:AddPermission",
      "lambda:RemovePermission",
      "lambda:GetPolicy",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:ListTags",
      "lambda:CreateEventSourceMapping",
      "lambda:GetEventSourceMapping",
      "lambda:UpdateEventSourceMapping",
      "lambda:DeleteEventSourceMapping",
      "lambda:ListEventSourceMappings",
    ]
    resources = ["arn:aws:lambda:*:*:function:capitol-lake-*"]
  }

  statement {
    sid = "PipelineQueues"
    actions = [
      "sqs:CreateQueue",
      "sqs:DeleteQueue",
      "sqs:GetQueueAttributes",
      "sqs:SetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ListQueueTags",
      "sqs:TagQueue",
      "sqs:UntagQueue",
    ]
    resources = [
      "arn:aws:sqs:*:*:house-collect-*",
      "arn:aws:sqs:*:*:senate-collect-*",
      "arn:aws:sqs:*:*:extract-*",
    ]
  }

  statement {
    sid = "HouseSchedule"
    actions = [
      "events:PutRule",
      "events:DeleteRule",
      "events:DescribeRule",
      "events:PutTargets",
      "events:RemoveTargets",
      "events:ListTargetsByRule",
      "events:ListTagsForResource",
      "events:TagResource",
      "events:UntagResource",
    ]
    resources = ["arn:aws:events:*:*:rule/capitol-lake-house-collect-schedule"]
  }

  statement {
    sid = "FinopsAlerts"
    actions = [
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:GetTopicAttributes",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:Unsubscribe",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = ["arn:aws:sns:*:*:capitol-lake-budget-alerts"]
  }

  statement {
    sid = "FinopsBudget"
    actions = [
      "budgets:ViewBudget",
      "budgets:ModifyBudget",
    ]
    resources = ["arn:aws:budgets::*:budget/capitol-lake-monthly"]
  }

  statement {
    sid = "FinopsStalenessAlarm"
    actions = [
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:DeleteAlarms",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]
    resources = ["arn:aws:cloudwatch:*:*:alarm:capitol-lake-pipeline-staleness"]
  }

  statement {
    sid       = "Secrets"
    actions   = ["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter", "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource", "ssm:ListTagsForResource"]
    resources = ["arn:aws:ssm:*:*:parameter/capitol-lake/*"]
  }
}

resource "aws_iam_role_policy" "github_actions_terraform" {
  name   = "terraform-apply"
  role   = aws_iam_role.github_actions_terraform.id
  policy = data.aws_iam_policy_document.github_actions_terraform.json
}
