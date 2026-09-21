#!/usr/bin/env bash
# One-time setup after cloning or creating a repo from this template.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

git config commit.template .gitmessage
git config core.hooksPath .githooks
chmod +x .githooks/* scripts/*

command -v uv >/dev/null || echo "warning: uv not found (needed by the hooks): https://docs.astral.sh/uv/"

# Create the integration branch if it does not exist yet.
if ! git rev-parse --verify --quiet HEAD >/dev/null; then
  echo "no commits yet: after your first commit on master, run 'git branch development'"
elif ! git show-ref --quiet refs/heads/development; then
  git branch development
  echo "created branch: development"
fi

echo "done. Next: protect master (see scripts/protect-master.sh)."
