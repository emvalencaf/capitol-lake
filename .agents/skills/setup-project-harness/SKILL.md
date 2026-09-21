---
name: setup-project-harness
description: "Set up a project created from this template: name and describe the project, configure CODE_STANDARDS.md and the matching pyproject.toml settings, and set up the issue tracker, triage label vocabulary, and domain doc layout. Run once before first use of the other skills."
disable-model-invocation: true
---

# Setup Project Harness

Set up a repo created from this template, then scaffold the per-repo configuration that the engineering skills assume:

- **Project identity**: the project name and one-line description, replacing the template placeholders
- **Code standards**: the stack section of `CODE_STANDARDS.md`, kept in sync with `pyproject.toml`
- **Issue tracker**: where issues live (GitHub by default; local markdown is also supported out of the box)
- **Triage labels**: the strings used for the five canonical triage roles
- **Usage tracking**: whether the status line logs per-session usage, and the budget for pay-per-token users
- **Domain docs**: where `CONTEXT.md` and ADRs live, and the consumer rules for reading them

This is a prompt-driven skill, not a deterministic script. Explore, present what you found, confirm with the user, then write.

## Process

### 1. Explore

Look at the current repo to understand its starting state. Read whatever exists; don't assume:

- `git remote -v` and `.git/config`: is this a GitHub repo? Which one?
- `AGENTS.md` and `CLAUDE.md` at the repo root: does either exist? Is there already an `## Agent skills` section in either?
- `CONTEXT.md` and `CONTEXT-MAP.md` at the repo root
- `docs/adr/` and any `src/*/docs/adr/` directories
- `docs/agents/`: does this skill's prior output already exist?
- `README.md`, `pyproject.toml` and `.wiki/index.md`: are they still the template placeholders (`Harness template` in the README header, `name = "project-name"`, `# Project knowledge`)? This decides whether Sections A and B run or are only confirmed.
- `CODE_STANDARDS.md`: does its **Stack** section still contain `_to be defined_`?
- `.claude/usage.conf`: does it exist, and is `USAGE_LOG` `on` or `off`? Is `scripts/usage-tracking.sh` present? (If the file or script is missing, Section F is skipped.)
- `.scratch/`: a sign that a local-markdown issue tracker convention is already in use
- Is the `triage` skill installed? (a `triage` skill folder alongside this one, or `triage` in your available skills.) This decides whether Section D runs at all.
- Monorepo signals: a `pnpm-workspace.yaml`, a `workspaces` field in `package.json`, or a populated `packages/*` with its own `src/`. These are present only in a genuinely large multi-package repo; their absence means single-context, which is almost every repo.

### 2. Present findings and ask

Summarise what's present and what's missing. Then take the sections in order. One section, one answer, then the next.

Lead each section with the recommended answer so the user can accept it in a word. Give a one-line explainer only when the choice genuinely branches; skip the section entirely when exploration already settled it (Section D when `triage` isn't installed, Section E when there's no monorepo, Section A when the name is already set).

**Section A: Project identity.** Skip when the placeholders are already replaced.

Ask for two things, one at a time:

> What is the project name? (a short kebab-case slug, e.g. `billing-api`; recommended: the repository directory name)
>
> One sentence: what does the project do?

Derive the variants from the slug: a **title** for prose (`Billing API`) and the **package name** for `pyproject.toml` (lowercase, letters, digits and hyphens only; it must be a valid PEP 508 name). Apply them to:

- `README.md`: it documents the template itself, so replace it with a new one generated from [README.template.md](./README.template.md), which follows the same section structure (see the **Documentation** section of `CODE_STANDARDS.md`). Copy the file and fill the `{{placeholders}}`: `{{project_title}}` and `{{project_description}}` from the answers above; `{{github_user}}` and `{{repo_name}}` from `git remote get-url origin` (ask if there is no remote); `{{author_name}}` from `git config user.name`; `{{license_text}}` as `Distributed under the <name> license. See LICENSE for more information.` if a `LICENSE` file exists, otherwise `No license has been chosen yet.`. Ask before overwriting a README that no longer contains `Harness template`. Remove sections that clearly do not apply, keep the back-to-top links, and delete the HTML guidance comments (such as `<!-- Say what problem it solves... -->`) once filled or irrelevant. Do not put an email address in the file; use the GitHub profile as the contact.
- `pyproject.toml`: set `[project].name` to the package name and add `description`.
- `.wiki/index.md`: change the `# Project knowledge` title to the project title; do the same in the title and description of `.wiki/getting-started.md`. Re-run `/validate .wiki --strict` afterwards.
- `CHANGELOG.md`: reset it to an empty `## [Unreleased]` section, dropping the template's own history.

If the GitHub repository is not yet named after the slug, mention `gh repo rename <slug>` and let the user decide; never rename it yourself.

**Section B: Code standards.** Skip only when the **Stack** section of `CODE_STANDARDS.md` has no `_to be defined_` left and the user says it is settled.

The template already assumes Python with `uv`, `ruff` and UTF-8, so don't re-ask what is decided. Ask the questions below one at a time, recommended answer first:

1. **Python version**: the minimum supported version (default `>=3.11`).
2. **Line length and lint rules**: ruff line length (default `100`) and rule sets (default `E, F, W, I, B, UP, N, RUF`). Offer to add more only if the user names a need (e.g. `S` for security, `D` for docstrings).
3. **Tests**: framework and command (default `pytest`, run as `uv run pytest`) and where tests live (default `tests/`).
4. **Types**: a type checker (`mypy`, `pyright`, or none; default none).
5. **Layout**: `src/<package>/` layout or a flat package (default `src/`).
6. **Docstrings**: style (Google, NumPy, or none; default none, since names and tests carry the intent).

Then write, and show the user a draft before doing so:

- **`CODE_STANDARDS.md`**: replace the placeholder note under the title and every `_to be defined_` in **Stack** with the answers: language and version, lint and format, type checker, test command, directory layout, docstring style. Keep the encoding line. Keep the **Skills** and later sections untouched.
- **`pyproject.toml`**: make it agree with the standards. Set `requires-python`, `[tool.ruff] line-length` and `target-version`, and `[tool.ruff.lint] select`. If a test framework or type checker was chosen, add its config table and list it under a `dev` dependency group (`uv add --dev <tool>`).
- **`.github/workflows/ci.yml`** (if present): append the test command and type check as steps so the server enforces what the standards say.

Never leave `CODE_STANDARDS.md` and `pyproject.toml` contradicting each other; `pyproject.toml` is the source of truth for tool settings, and the standards document names it instead of repeating values that could drift.

**Section C: Issue tracker.**

> Explainer: The "issue tracker" is where issues live for this repo. Skills like `to-tickets`, `triage`, and `to-spec` read from and write to it. They need to know whether to call `gh issue create`, write a markdown file under `.scratch/`, or follow some other workflow you describe. Pick the place you actually track work for this repo.

Default posture: these skills were designed for GitHub. If a `git remote` points at GitHub, propose that. If a `git remote` points at GitLab (`gitlab.com` or a self-hosted host), propose GitLab. Otherwise (or if the user prefers), offer:

- **GitHub**: issues live in the repo's GitHub Issues (uses the `gh` CLI)
- **GitLab**: issues live in the repo's GitLab Issues (uses the [`glab`](https://gitlab.com/gitlab-org/cli) CLI)
- **Local markdown**: issues live as files under `.scratch/<feature>/` in this repo (good for solo projects or repos without a remote)
- **Other** (Jira, Linear, etc.): ask the user to describe the workflow in one paragraph; the skill will record it as freeform prose

Record the choice in `docs/agents/issue-tracker.md`. The GitHub and GitLab templates carry a "PRs as a request surface" flag, defaulted **off**. Leave it off and don't raise it: a user who wants external PRs in the triage queue can flip the flag in the file later.

**Section D: Triage label vocabulary.** Skip this section entirely if the `triage` skill isn't installed (exploration told you), since an uninstalled skill needs no labels.

If it is installed, ask exactly one question:

> Do you want to keep the default triage labels? (recommended: **yes**)

The defaults are the five canonical roles, each label string equal to its name: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. On **yes**, write them as-is. Only if the user says no, usually because their tracker already uses other names (e.g. `bug:triage` for `needs-triage`), collect the overrides so `triage` applies existing labels instead of creating duplicates.

**Section E: Domain docs.** Default to **single-context** (one `CONTEXT.md` + `docs/adr/` at the repo root). This fits almost every repo; write it without asking.

Offer **multi-context** (a root `CONTEXT-MAP.md` pointing to per-context `CONTEXT.md` files) only when exploration found monorepo signals. Then confirm which layout they want.

**Section F: Usage tracking.** Skip when `.claude/usage.conf` and `scripts/usage-tracking.sh` do not exist.

Explain in one sentence: the status line can record one small JSON file per session in `.claude/usage/` (git-ignored, numbers and metadata only, no conversation content), which `/usage-report` turns into a dashboard. The cost it records is Claude Code's own estimate, not an invoice. Then ask exactly one question:

> Keep usage tracking on? (recommended: **yes**)

Apply the answer with `scripts/usage-tracking.sh on` or `scripts/usage-tracking.sh off`. If the script is missing, write `USAGE_LOG=on` or `USAGE_LOG=off` into `.claude/usage.conf` directly.

Then, only when `scripts/set-budget.sh` exists, ask:

> Do you pay per token, without a Claude subscription? (recommended: ask only if unsure; subscriptions show rate limits instead of a budget)

If yes, ask for the budget in USD and run `scripts/set-budget.sh <usd>`; offer `--global` if they want the same budget in every project. If no, leave the default.

### 3. Confirm and edit

Show the user a draft of:

- The changes for Sections A and B (the generated `README.md`, `pyproject.toml`, `.wiki/`, `CODE_STANDARDS.md`)
- The usage tracking and budget choices from Section F
- The `## Agent skills` block to add to whichever of `CLAUDE.md` / `AGENTS.md` is being edited (see step 4 for selection rules)
- The contents of `docs/agents/issue-tracker.md`, `docs/agents/domain.md`, and `docs/agents/triage-labels.md` (the last only when `triage` is installed)

Let them edit before writing.

### 4. Write

**Pick the file to edit:**

- If `CLAUDE.md` exists, edit it.
- Else if `AGENTS.md` exists, edit it.
- If neither exists, ask the user which one to create; don't pick for them.

Never create `AGENTS.md` when `CLAUDE.md` already exists (or vice versa); always edit the one that's already there.

If an `## Agent skills` block already exists in the chosen file, update its contents in-place rather than appending a duplicate. Don't overwrite user edits to the surrounding sections.

The block:

```markdown
## Agent skills

### Issue tracker

[one-line summary of where issues are tracked]. See `docs/agents/issue-tracker.md`.

### Triage labels

[one-line summary of the label vocabulary]. See `docs/agents/triage-labels.md`.

### Domain docs

[one-line summary of layout: "single-context" or "multi-context"]. See `docs/agents/domain.md`.
```

Include the `### Triage labels` sub-block, and write `docs/agents/triage-labels.md`, only when `triage` is installed and Section D ran. When it isn't, both are omitted.

Then write the docs files using the seed templates in this skill folder as a starting point:

- [issue-tracker-github.md](./issue-tracker-github.md): GitHub issue tracker
- [issue-tracker-gitlab.md](./issue-tracker-gitlab.md): GitLab issue tracker
- [issue-tracker-local.md](./issue-tracker-local.md): local-markdown issue tracker
- [triage-labels.md](./triage-labels.md): label mapping (only if `triage` is installed)
- [domain.md](./domain.md): domain doc consumer rules + layout

For "other" issue trackers, write `docs/agents/issue-tracker.md` from scratch using the user's description.

### 5. Done

Tell the user the setup is complete: what was renamed, which standards were set, and which engineering skills will now read `docs/agents/*.md`. Remind them to commit on a work branch cut from `development`, following [CONTRIBUTING.md](../../../CONTRIBUTING.md) (for example `chore(setup): configure project name and standards`). Mention they can edit `docs/agents/*.md` directly later; re-running this skill is only necessary if they want to switch issue trackers or restart from scratch.
