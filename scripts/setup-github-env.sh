#!/usr/bin/env bash
# Automates infra/README.md's "One-time GitHub setup" (#46) for the infra
# CI/CD pipeline (.github/workflows/infra-cicd.yml): a protected GitHub
# Environment gating `terraform apply`, plus the repo secrets `plan`/`apply`
# read via OIDC.
#
#   scripts/setup-github-env.sh up    create/update the Environment + secrets
#   scripts/setup-github-env.sh down  remove the secrets and the Environment
#   scripts/setup-github-env.sh down --purge-history
#                                     ^ also deletes every infra-cicd.yml
#                                       workflow run and every deployment
#                                       recorded against the Environment.
#                                       Irreversible — GitHub keeps no trash
#                                       can for either. Asks for a second,
#                                       separate confirmation.
#
# Requires: gh (authenticated), terraform, and infra/bootstrap already
# applied (its outputs feed AWS_ROLE_ARN / TF_STATE_BUCKET below — see
# infra/README.md step 1).
#
# Inputs (env vars):
#   FINOPS_ALERT_EMAIL   required for `up` — same value passed to
#                        `terraform apply -var=finops_alert_email=...`
#   GH_REVIEWER          GitHub username(s) required to approve `apply` runs,
#                        comma-separated. Required for `up` unless
#                        --no-reviewer is passed (leaves the Environment
#                        without a reviewer gate, i.e. NOT actually
#                        protected — infra/README.md's whole point).
#   GITHUB_ENVIRONMENT   Environment name (default: production; must match
#                        `environment:` in infra-cicd.yml and
#                        var.github_environment in infra/bootstrap).
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
bootstrap_dir="$root/infra/bootstrap"
env_name="${GITHUB_ENVIRONMENT:-production}"
no_reviewer=0
purge_history=0

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required tool: $1" >&2
    exit 1
  }
}

usage() {
  sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

cmd="${1:-}"
shift || true
for arg in "$@"; do
  case "$arg" in
    --no-reviewer) no_reviewer=1 ;;
    --purge-history) purge_history=1 ;;
    *)
      echo "unknown argument: $arg" >&2
      usage 1
      ;;
  esac
done

case "$cmd" in
  up | down) ;;
  -h | --help) usage ;;
  *) usage 1 ;;
esac

require gh
require terraform

gh auth status >/dev/null 2>&1 || {
  echo "gh is not authenticated — run 'gh auth login' first" >&2
  exit 1
}

repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
owner="${repo%%/*}"
name="${repo##*/}"

case "$cmd" in
  up)
    [[ -n "${FINOPS_ALERT_EMAIL:-}" ]] || {
      echo "set FINOPS_ALERT_EMAIL (var.finops_alert_email has no default)" >&2
      exit 1
    }
    if (( ! no_reviewer )) && [[ -z "${GH_REVIEWER:-}" ]]; then
      echo "set GH_REVIEWER=<username[,username...]> (required reviewer for the '$env_name' Environment)," >&2
      echo "or pass --no-reviewer to create it unprotected (not recommended, see infra/README.md)" >&2
      exit 1
    fi

    [[ -d "$bootstrap_dir/.terraform" ]] || {
      echo "infra/bootstrap has no local state — run its 'terraform init && terraform apply' first (infra/README.md step 1)" >&2
      exit 1
    }

    echo "==> reading infra/bootstrap outputs"
    role_arn="$(terraform -chdir="$bootstrap_dir" output -raw github_actions_role_arn)"
    state_bucket="$(terraform -chdir="$bootstrap_dir" output -raw state_bucket_name)"
    [[ -n "$role_arn" && -n "$state_bucket" ]] || {
      echo "empty terraform output — has 'terraform apply' run in infra/bootstrap?" >&2
      exit 1
    }

    echo "==> creating/updating GitHub Environment '$env_name' on $repo"
    # GitHub treats a present-but-empty "reviewers" array as "enable the
    # required-reviewers protection rule with zero reviewers", which 422s on
    # plans/repo visibilities that don't support that rule at all (private
    # repos need GitHub Team/Enterprise; public repos get it on any plan).
    # So --no-reviewer must omit the key entirely, not send `[]`.
    if (( no_reviewer )); then
      api_payload='{"deployment_branch_policy":null}'
    else
      reviewers_json="["
      first=1
      IFS=',' read -ra usernames <<< "$GH_REVIEWER"
      for u in "${usernames[@]}"; do
        u="$(echo "$u" | xargs)" # trim whitespace
        uid="$(gh api "users/$u" --jq .id)"
        [[ -n "$uid" ]] || {
          echo "could not resolve GitHub user id for '$u'" >&2
          exit 1
        }
        (( first )) || reviewers_json+=","
        reviewers_json+="{\"type\":\"User\",\"id\":$uid}"
        first=0
      done
      reviewers_json+="]"
      api_payload="$(printf '{"deployment_branch_policy":null,"reviewers":%s}' "$reviewers_json")"
    fi

    if ! echo "$api_payload" | gh api \
      --method PUT \
      "repos/$owner/$name/environments/$env_name" \
      --input - >/dev/null 2>&1; then
      if (( ! no_reviewer )); then
        echo "failed to create/update the Environment with a required reviewer." >&2
        echo "GitHub's required-reviewers protection rule needs GitHub Team/Enterprise" >&2
        echo "on a private repo (public repos get it on any plan). Either upgrade the" >&2
        echo "plan, make the repo public, or re-run with --no-reviewer to create the" >&2
        echo "Environment without the gate for now." >&2
        exit 1
      fi
      echo "failed to create/update the Environment '$env_name'" >&2
      exit 1
    fi
    if (( no_reviewer )); then
      echo "    (no reviewer set — Environment exists but is NOT gated; see infra/README.md)"
    else
      echo "    required reviewer(s): $GH_REVIEWER"
    fi

    echo "==> setting repo secrets"
    gh secret set AWS_ROLE_ARN --repo "$repo" --body "$role_arn"
    gh secret set TF_STATE_BUCKET --repo "$repo" --body "$state_bucket"
    gh secret set FINOPS_ALERT_EMAIL --repo "$repo" --body "$FINOPS_ALERT_EMAIL"

    echo "==> done — .github/workflows/infra-cicd.yml can now run plan/apply"
    ;;

  down)
    echo "This removes the '$env_name' GitHub Environment and its secrets"
    echo "(AWS_ROLE_ARN, TF_STATE_BUCKET, FINOPS_ALERT_EMAIL) from $repo."
    read -r -p "Type the repo name ($repo) to confirm: " confirm_repo
    [[ "$confirm_repo" == "$repo" ]] || {
      echo "repo name mismatch, aborting" >&2
      exit 1
    }

    echo "==> removing repo secrets"
    for secret in AWS_ROLE_ARN TF_STATE_BUCKET FINOPS_ALERT_EMAIL; do
      gh secret delete "$secret" --repo "$repo" 2>/dev/null || echo "    (skipped $secret — not set)"
    done

    echo "==> deleting GitHub Environment '$env_name'"
    gh api --method DELETE "repos/$owner/$name/environments/$env_name" 2>/dev/null \
      || echo "    (skipped — Environment '$env_name' didn't exist)"

    if (( purge_history )); then
      echo
      echo "--purge-history also deletes:"
      echo "  - every run of the 'Infra CI/CD' workflow (infra-cicd.yml)"
      echo "  - every deployment recorded against the '$env_name' environment"
      echo "Both are permanent — GitHub has no undo for either."
      read -r -p "Type 'purge' to confirm: " confirm_purge
      [[ "$confirm_purge" == "purge" ]] || {
        echo "purge not confirmed, skipping history cleanup" >&2
        exit 1
      }

      echo "==> deleting infra-cicd.yml workflow runs"
      run_ids="$(gh api "repos/$owner/$name/actions/workflows/infra-cicd.yml/runs" \
        --paginate --jq '.workflow_runs[].id' 2>/dev/null || true)"
      if [[ -z "$run_ids" ]]; then
        echo "    (none found)"
      else
        while IFS= read -r run_id; do
          gh api --method DELETE "repos/$owner/$name/actions/runs/$run_id" >/dev/null 2>&1 \
            && echo "    deleted run $run_id" \
            || echo "    (failed to delete run $run_id, skipping)"
        done <<< "$run_ids"
      fi

      echo "==> deleting deployments for environment '$env_name'"
      deployment_ids="$(gh api "repos/$owner/$name/deployments?environment=$env_name" \
        --paginate --jq '.[].id' 2>/dev/null || true)"
      if [[ -z "$deployment_ids" ]]; then
        echo "    (none found)"
      else
        while IFS= read -r deployment_id; do
          # A deployment must be marked inactive before GitHub allows deleting it.
          gh api --method POST "repos/$owner/$name/deployments/$deployment_id/statuses" \
            -f state=inactive >/dev/null 2>&1 || true
          gh api --method DELETE "repos/$owner/$name/deployments/$deployment_id" >/dev/null 2>&1 \
            && echo "    deleted deployment $deployment_id" \
            || echo "    (failed to delete deployment $deployment_id, skipping)"
        done <<< "$deployment_ids"
      fi
    fi

    echo "==> done"
    ;;
esac
