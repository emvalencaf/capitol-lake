#!/usr/bin/env bash
# Builds, deploys, invokes, and tears down the standalone Senate-Akamai
# probe Lambda (#29) — infra/probes/senate-akamai-probe/, never part of the
# main stack or its CI/CD apply gate. Automates the manual steps in that
# directory's README.md; read it first for the full context.
#
#   scripts/deploy-senate-akamai-probe.sh up                   build, push, apply
#   scripts/deploy-senate-akamai-probe.sh invoke <filing-id>   invoke once, print the result
#   scripts/deploy-senate-akamai-probe.sh down                 terraform destroy
#
# Requires: terraform, docker, aws CLI — all already authenticated against
# the target AWS account (same credentials infra/'s main stack would use).
# Region defaults to us-east-1 (matching variables.tf); override with
# AWS_REGION.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
probe_dir="$root/infra/probes/senate-akamai-probe"
dockerfile="$root/docker/senate_akamai_probe.Dockerfile"
region="${AWS_REGION:-us-east-1}"
image_tag="latest"

tf() { terraform -chdir="$probe_dir" "$@"; }

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    exit 1
  }
}

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

cmd="${1:-}"
case "$cmd" in
  up | invoke | down) ;;
  -h | --help) usage ;;
  *) usage 1 ;;
esac

require terraform
require docker
require aws

tf init -input=false

case "$cmd" in
  up)
    echo "==> creating the ECR repository only (target-only apply; image isn't built yet)"
    tf apply -input=false -auto-approve \
      -target=aws_ecr_repository.probe \
      -var="aws_region=${region}" \
      -var="image_uri=pending"

    repo_url="$(tf output -raw ecr_repository_url)"
    image_uri="${repo_url}:${image_tag}"

    echo "==> building $dockerfile (UNVERIFIED per its header comment — watch for build errors)"
    docker build -f "$dockerfile" -t "$image_uri" "$root"

    echo "==> pushing $image_uri"
    aws ecr get-login-password --region "$region" \
      | docker login --username AWS --password-stdin "${repo_url%%/*}"
    docker push "$image_uri"

    echo "==> applying the full stack, pointing the Lambda at the pushed image"
    tf apply -input=false -auto-approve \
      -var="aws_region=${region}" \
      -var="image_uri=${image_uri}"

    echo "==> done. function: $(tf output -raw function_name)"
    echo "Next: $0 invoke <a real /ptr/ filing uuid>"
    ;;

  invoke)
    filing_id="${2:-}"
    [[ -z "$filing_id" ]] && {
      echo "usage: $0 invoke <filing-id>" >&2
      exit 1
    }
    function_name="$(tf output -raw function_name)"
    out_file="$(mktemp)"
    trap 'rm -f "$out_file"' EXIT

    aws lambda invoke --function-name "$function_name" --region "$region" \
      --payload "{\"filing_id\": \"${filing_id}\"}" \
      --cli-binary-format raw-in-base64-out \
      "$out_file" >/dev/null
    cat "$out_file"
    echo
    echo "Record this result in docs/research/senate-akamai-lambda-probe.md"
    ;;

  down)
    tf destroy -input=false -var="aws_region=${region}" -var="image_uri=pending"
    ;;
esac
