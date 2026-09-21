#!/usr/bin/env bash
# Protects master on GitHub: PRs only, no force pushes. Requires gh auth.
set -euo pipefail
repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
gh api -X PUT "repos/${repo}/branches/master/protection" --input - <<JSON
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 1 },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "master is now protected on ${repo}"
