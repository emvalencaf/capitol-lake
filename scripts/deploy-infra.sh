#!/usr/bin/env bash
# Automates the main stack's first-deploy chicken-and-egg problem (#46,
# infra/README.md): every pipeline Lambda is package_type = "Image" pointing
# at "<its ECR repo>:latest" (infra/modules/pipeline/main.tf), but on a fresh
# account that repo is empty when Terraform first tries to create the
# Lambda, so `terraform apply` fails with "Provide a valid source image."
# This script applies the ECR repositories first, builds and pushes each
# stage's image, then applies the rest of the stack — the same three-step
# dance the now-retired senate-akamai-probe standalone Lambda used (#70),
# generalized to the 4 stages here.
#
#   scripts/deploy-infra.sh up      init, create ECR repos, build+push images, full apply
#   scripts/deploy-infra.sh plan    init, terraform plan (no image build/push)
#   scripts/deploy-infra.sh down    terraform destroy (asks for confirmation)
#
# Requires: terraform, docker, aws CLI — all already authenticated
# against the target AWS account (same credentials CI's OIDC role would use).
# Requires infra/backend.hcl (see infra/README.md step 1) and the
# FINOPS_ALERT_EMAIL environment variable (var.finops_alert_email has no
# default). Region defaults to us-east-1 (matching variables.tf); override
# with AWS_REGION.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
infra_dir="$root/infra"
region="${AWS_REGION:-us-east-1}"
image_tag="latest"

# stage name -> Dockerfile, matching infra/modules/pipeline/main.tf's
# aws_ecr_repository.this keys and docker/*.Dockerfile's naming.
stages=(house-collect senate-collect senate-collect-automated extract)
dockerfile_for() {
  case "$1" in
    house-collect) echo "docker/house_collect.Dockerfile" ;;
    senate-collect) echo "docker/senate_collect.Dockerfile" ;;
    senate-collect-automated) echo "docker/senate_collect_automated.Dockerfile" ;;
    extract) echo "docker/extract.Dockerfile" ;;
  esac
}

tf() { terraform -chdir="$infra_dir" "$@"; }

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    exit 1
  }
}

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

cmd="${1:-}"
case "$cmd" in
  up | plan | down) ;;
  -h | --help) usage ;;
  *) usage 1 ;;
esac

require terraform
require docker
require aws

[[ -f "$infra_dir/backend.hcl" ]] || {
  echo "missing infra/backend.hcl — see infra/README.md step 1 (bootstrap) first" >&2
  exit 1
}

[[ -n "${FINOPS_ALERT_EMAIL:-}" ]] || {
  echo "set FINOPS_ALERT_EMAIL (var.finops_alert_email has no default)" >&2
  exit 1
}

tf init -input=false -backend-config=backend.hcl

case "$cmd" in
  plan)
    tf plan -input=false -var="finops_alert_email=${FINOPS_ALERT_EMAIL}"
    ;;

  up)
    echo "==> creating the ECR repositories only (target-only apply; images aren't built yet)"
    tf apply -input=false -auto-approve \
      -target='module.pipeline.aws_ecr_repository.this' \
      -var="finops_alert_email=${FINOPS_ALERT_EMAIL}"

    account_id="$(aws sts get-caller-identity --query Account --output text)"
    registry="${account_id}.dkr.ecr.${region}.amazonaws.com"

    echo "==> logging in to $registry"
    aws ecr get-login-password --region "$region" \
      | docker login --username AWS --password-stdin "$registry"

    for stage in "${stages[@]}"; do
      dockerfile="$root/$(dockerfile_for "$stage")"
      repo="capitol-lake-${stage}"
      image_uri="${registry}/${repo}:${image_tag}"

      echo "==> building $dockerfile -> $image_uri"
      docker build -f "$dockerfile" -t "$image_uri" "$root"

      echo "==> pushing $image_uri"
      docker push "$image_uri"
    done

    echo "==> applying the full stack"
    tf apply -input=false -auto-approve \
      -var="finops_alert_email=${FINOPS_ALERT_EMAIL}"

    # Every stage's image_uri uses the mutable ":latest" tag (the same
    # limitation the now-retired senate-akamai-probe script documented), so
    # re-running `up` after a code fix pushes a new digest behind the same
    # string — Terraform sees no diff and won't redeploy it. Force each
    # Lambda onto the just-pushed image explicitly; harmless when the
    # digest is already current.
    for stage in "${stages[@]}"; do
      function_name="capitol-lake-${stage}"
      repo="capitol-lake-${stage}"
      image_uri="${registry}/${repo}:${image_tag}"

      echo "==> forcing $function_name onto the just-pushed image"
      aws lambda update-function-code --region "$region" \
        --function-name "$function_name" \
        --image-uri "$image_uri" >/dev/null
      aws lambda wait function-updated --region "$region" --function-name "$function_name"
    done

    echo "==> done"
    ;;

  down)
    echo "This runs 'terraform destroy' against the real AWS stack."
    read -r -p "Type the stack's AWS account id to confirm: " confirm_account_id
    account_id="$(aws sts get-caller-identity --query Account --output text)"
    [[ "$confirm_account_id" == "$account_id" ]] || {
      echo "account id mismatch, aborting" >&2
      exit 1
    }
    tf destroy -input=false -var="finops_alert_email=${FINOPS_ALERT_EMAIL}"
    ;;
esac
