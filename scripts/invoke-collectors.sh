#!/usr/bin/env bash
# Manually invokes the House and/or automated Senate collector Lambdas
# (normally EventBridge-scheduled, infra/modules/scheduling), so you don't
# have to wait out the rate(1 day) schedule to see a run happen. Prints the
# invoke result, tails recent CloudWatch logs, and lists what landed in the
# Bronze bucket.
#
#   scripts/invoke-collectors.sh house [year]   invoke capitol-lake-house-collect (default year: this year)
#   scripts/invoke-collectors.sh senate         invoke capitol-lake-senate-collect-automated (no payload; may take up to 15 minutes)
#   scripts/invoke-collectors.sh all [year]     invoke both, one after another
#
# Requires: aws CLI, terraform — already authenticated against the target
# AWS account. Reads the project bucket name from `terraform output` in
# infra/ (bronze/silver are key prefixes inside it, not separate buckets),
# so infra/backend.hcl must already be configured. Region defaults to
# us-east-1 (matching infra/variables.tf); override with AWS_REGION.
set -euo pipefail

# The AWS CLI v2 pages every command's stdout through `less` by default on
# an interactive terminal, which blocks this script mid-run waiting for a
# keypress (e.g. right after `aws lambda invoke` prints its status JSON).
export AWS_PAGER=""

root="$(git rev-parse --show-toplevel)"
infra_dir="$root/infra"
region="${AWS_REGION:-us-east-1}"

tf() { terraform -chdir="$infra_dir" "$@"; }

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    exit 1
  }
}

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

cmd="${1:-}"
case "$cmd" in
  house | senate | all) ;;
  -h | --help) usage ;;
  *) usage 1 ;;
esac

require aws
require terraform

bucket_name="$(tf output -raw bucket_name)"

show_result() {
  local out_file="$1"
  local invoke_status="$2"
  echo "==> result:"
  cat "$out_file"
  echo
  if grep -q '"FunctionError"' <<<"$invoke_status"; then
    echo "==> FUNCTION ERROR — the Lambda ran but raised an exception (see payload above and the logs below)"
  fi
}

tail_logs() {
  local function_name="$1"
  echo "==> recent logs for $function_name"
  aws logs tail "/aws/lambda/${function_name}" --region "$region" --since 10m || true
}

list_bronze() {
  local prefix="$1"
  echo "==> recent Bronze objects under $prefix"
  aws s3api list-objects-v2 --bucket "$bucket_name" --prefix "$prefix" \
    --region "$region" --query 'reverse(sort_by(Contents, &LastModified))[:10].[Key,LastModified]' \
    --output table 2>/dev/null || echo "(no objects yet, or prefix doesn't exist)"
}

invoke_house() {
  local year="${1:-$(date +%Y)}"
  local function_name="capitol-lake-house-collect"
  local out_file
  out_file="$(mktemp)"
  trap 'rm -f "$out_file"' RETURN

  echo "==> invoking $function_name (year=$year; a full-year backfill can run close to its 900s Lambda timeout)"
  local invoke_status
  invoke_status="$(aws lambda invoke \
    --function-name "$function_name" \
    --region "$region" \
    --payload "{\"year\": ${year}}" \
    --cli-binary-format raw-in-base64-out \
    --cli-read-timeout 0 \
    "$out_file")"

  show_result "$out_file" "$invoke_status"
  tail_logs "$function_name"
  list_bronze "bronze/house/"
}

invoke_senate() {
  local function_name="capitol-lake-senate-collect-automated"
  local out_file
  out_file="$(mktemp)"
  trap 'rm -f "$out_file"' RETURN

  echo "==> invoking $function_name (no payload; a real headless-browser session, can take up to 15 minutes)"
  local invoke_status
  invoke_status="$(aws lambda invoke \
    --function-name "$function_name" \
    --region "$region" \
    --cli-read-timeout 0 \
    "$out_file")"

  show_result "$out_file" "$invoke_status"
  tail_logs "$function_name"
  list_bronze "bronze/senate/"
}

case "$cmd" in
  house) invoke_house "${2:-}" ;;
  senate) invoke_senate ;;
  all)
    invoke_house "${2:-}"
    invoke_senate
    ;;
esac
