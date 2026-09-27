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
#
# This repo has "immutable subject claims" enabled (GitHub Settings > Actions
# > General > OIDC customization; `gh api repos/<repo>/actions/oidc/customization/sub`
# shows `use_immutable_subject: true`) — it's the account-recommended default,
# closing the hijack window where deleting/renaming a repo and recreating one
# with the same owner/name would otherwise inherit any trust policy scoped by
# name alone. With it on, GitHub's `sub` embeds each side's numeric,
# never-reused id: `repo:<owner>@<owner_id>/<repo>@<repo_id>:pull_request`
# instead of the classic `repo:<owner>/<repo>:pull_request`. `local.sub_*`
# below wildcards past those ids (StringLike, not StringEquals) so this trust
# policy matches either form without hardcoding this AWS account's specific
# owner/repo id pair — those ids aren't a Terraform input anywhere else, and
# baking them in would silently start failing if GitHub ever rotates them.
locals {
  github_repository_parts = split("/", var.github_repository)
  github_owner            = local.github_repository_parts[0]
  github_repo_name        = local.github_repository_parts[1]
  sub_pull_request        = "repo:${local.github_owner}*/${local.github_repo_name}*:pull_request"
  sub_environment         = "repo:${local.github_owner}*/${local.github_repo_name}*:environment:${var.github_environment}"
}

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
        local.sub_pull_request,
        local.sub_environment,
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
      "s3:GetBucketAcl",
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
      # aws_s3_bucket's read (refresh) also fetches every one of these
      # deprecated/computed legacy attributes regardless of whether they're
      # set, even though modules/storage doesn't configure any of them —
      # AWS provider v5 backward-compat behavior for the all-in-one
      # aws_s3_bucket resource, not this stack's own design.
      "s3:GetBucketCORS",
      "s3:GetBucketLogging",
      "s3:GetBucketWebsite",
      "s3:GetBucketRequestPayment",
      "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketObjectLockConfiguration",
    ]
    # var.bucket_prefix's default (modules/storage's aws_s3_bucket.this) is
    # the bare name "capitol-lake" (bronze/silver unified into key prefixes
    # inside it, #18) — no trailing "-*" the "capitol-lake-*" pattern this
    # used to require needs to match against. Bare wildcard instead, so it
    # covers that bucket and any future "capitol-lake*"-named one.
    resources = [
      "arn:aws:s3:::capitol-lake*",
      "arn:aws:s3:::capitol-lake*/*",
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
      "lambda:ListVersionsByFunction",
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

  # Covers both EventBridge schedules modules/scheduling/main.tf creates
  # (capitol-lake-house-collect-schedule, capitol-lake-senate-collect-
  # automated-schedule) — a single "*-schedule" pattern rather than one
  # entry per rule, since they're both this stack's only rule type.
  statement {
    sid = "PipelineSchedules"
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
    resources = ["arn:aws:events:*:*:rule/capitol-lake-*-schedule"]
  }

  # aws_lambda_event_source_mapping resources (modules/lambda-stage) get a
  # GitHub-assigned UUID, not a "capitol-lake"-prefixed name, so unlike every
  # other statement here this can't be scoped by name — same reasoning as
  # SecretsDescribe below for ssm:DescribeParameters.
  statement {
    sid = "LambdaEventSourceMappings"
    actions = [
      "lambda:CreateEventSourceMapping",
      "lambda:GetEventSourceMapping",
      "lambda:UpdateEventSourceMapping",
      "lambda:DeleteEventSourceMapping",
      "lambda:ListEventSourceMappings",
      "lambda:ListTags",
    ]
    resources = ["arn:aws:lambda:*:*:event-source-mapping:*"]
  }

  statement {
    sid = "FinopsAlerts"
    actions = [
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:GetTopicAttributes",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = ["arn:aws:sns:*:*:capitol-lake-budget-alerts"]
  }

  # aws_sns_topic_subscription's own actions (refresh's GetSubscriptionAttributes,
  # and Unsubscribe on destroy/replace) take a subscription ARN as the API
  # parameter, but AWS evaluates identity-policy resource matching against
  # the *topic* ARN (confirmed via CloudTrail/simulate-principal-policy —
  # the AccessDenied message's "on resource" already truncates to the topic
  # ARN, no subscription-id suffix). Both forms listed since that's
  # undocumented behavior this policy shouldn't depend on staying exactly
  # this way.
  statement {
    sid = "FinopsAlertsSubscription"
    actions = [
      "sns:GetSubscriptionAttributes",
      "sns:Unsubscribe",
    ]
    resources = [
      "arn:aws:sns:*:*:capitol-lake-budget-alerts",
      "arn:aws:sns:*:*:capitol-lake-budget-alerts:*",
    ]
  }

  statement {
    sid = "FinopsBudget"
    actions = [
      "budgets:ViewBudget",
      "budgets:ModifyBudget",
      "budgets:ListTagsForResource",
    ]
    resources = ["arn:aws:budgets::*:budget/capitol-lake-monthly"]
  }

  # Covers both alarms modules/finops/main.tf creates (capitol-lake-pipeline-
  # staleness, capitol-lake-senate-collect-automated-errors, #69) under one
  # "capitol-lake-*" pattern rather than one entry per alarm.
  statement {
    sid = "FinopsAlarms"
    actions = [
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:DeleteAlarms",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]
    resources = ["arn:aws:cloudwatch:*:*:alarm:capitol-lake-*"]
  }

  statement {
    sid       = "Secrets"
    actions   = ["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter", "ssm:AddTagsToResource", "ssm:RemoveTagsFromResource", "ssm:ListTagsForResource"]
    resources = ["arn:aws:ssm:*:*:parameter/capitol-lake/*"]
  }

  # ssm:DescribeParameters has no resource-level permissions (AWS requires
  # "*" for it — the aws_ssm_parameter data/resource's own refresh calls it
  # to look up each parameter's metadata before the scoped GetParameter
  # above). Read-only; lists parameter names/metadata, never secret values.
  statement {
    sid       = "SecretsDescribe"
    actions   = ["ssm:DescribeParameters"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions_terraform" {
  name   = "terraform-apply"
  role   = aws_iam_role.github_actions_terraform.id
  policy = data.aws_iam_policy_document.github_actions_terraform.json
}
