# Root module: composes the per-concern modules (ADR-0009) into the
# deployable stack. Building/pushing each stage's container image and
# populating the SSM secret values are out of scope (#44 is infra only,
# not deployment) — see infra/README.md.

module "storage" {
  source = "./modules/storage"

  bucket_prefix = var.bucket_prefix
  tags          = var.common_tags
}

module "pipeline" {
  source = "./modules/pipeline"

  bronze_bucket_name = module.storage.bronze_bucket_name
  bronze_bucket_arn  = module.storage.bronze_bucket_arn
  silver_bucket_name = module.storage.silver_bucket_name
  silver_bucket_arn  = module.storage.silver_bucket_arn

  ecr_repo_prefix            = var.ecr_repo_prefix
  llm_fallback_provider      = var.llm_fallback_provider
  stage_reserved_concurrency = var.stage_reserved_concurrency
  tags                       = var.common_tags
}

module "scheduling" {
  source = "./modules/scheduling"

  house_collect_function_name = module.pipeline.house_collect_function_name
  house_collect_function_arn  = module.pipeline.house_collect_function_arn
  house_filing_year           = var.house_filing_year
  house_schedule_expression   = var.house_schedule_expression

  senate_collect_automated_function_name = module.pipeline.senate_collect_automated_function_name
  senate_collect_automated_function_arn  = module.pipeline.senate_collect_automated_function_arn
  senate_automated_schedule_expression   = var.senate_automated_schedule_expression

  extract_function_name = module.pipeline.extract_function_name
  extract_function_arn  = module.pipeline.extract_function_arn

  bronze_bucket_id  = module.storage.bronze_bucket_id
  bronze_bucket_arn = module.storage.bronze_bucket_arn

  tags = var.common_tags
}

module "finops" {
  source = "./modules/finops"

  alert_email = var.finops_alert_email

  budget_amount_usd = var.budget_amount_usd

  staleness_function_name  = module.pipeline.house_collect_function_name
  staleness_period_seconds = var.house_schedule_period_seconds

  senate_automated_function_name        = module.pipeline.senate_collect_automated_function_name
  senate_automated_error_period_seconds = var.senate_automated_error_period_seconds

  tags = var.common_tags
}
