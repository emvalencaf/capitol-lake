# Contributing

> First time here? Run `scripts/setup.sh` to enable the git hooks: `pre-commit`
> (Unicode check, ruff lint/format, and `.wiki/` update when code changes — skip
> the last with `SKIP_WIKI_UPDATE=1`) and `commit-msg` (enforces the format below).

## Branch strategy

```
master  ◄── PR ── development ◄── PR ── <tag>/<short-description>
(protected)        (integration)         (work branches)
```

- **`master`** is protected. No direct pushes, no direct work. It only receives
  PRs from `development`.
- **`development`** is the integration branch. It only receives PRs from work
  branches and is the base for all new work.
- **Work branches** are always cut from an up-to-date `development`, and merged
  back into it by PR when finished.

Workflow:

1. `git switch development && git pull`
2. `git switch -c <tag>/<short-description>` (e.g. `feat/query-skill`)
3. Commit following the convention below.
4. Open a PR **into `development`**. Keep the branch after merge (do not
   delete it) so work stays traceable.
5. To release, open a PR from `development` **into `master`** and update
   [CHANGELOG.md](CHANGELOG.md).

Branch names use the same `tag` list as commits, lowercase, words separated by
`-`.

## Commit convention

Commits are **always written in English**.

### Title

```
tag(subject/subsubject): short summary
```

- `tag` — one of:

  | Tag | Use for |
  |---|---|
  | `feat` | new capability or skill |
  | `fix` | bug fix |
  | `docs` | documentation only |
  | `refactor` | restructuring without behavior change |
  | `style` | formatting, wording, no behavior change |
  | `test` | adding or changing tests |
  | `chore` | tooling, lockfiles, housekeeping |
  | `build` / `ci` | build system / CI configuration |
  | `perf` | performance |
  | `revert` | reverting an earlier commit |

- `subject/subsubject` — the area touched, from broad to narrow, e.g.
  `skills/query`, `docs/contributing`. `subsubject` is optional:
  `feat(skills): ...` is valid.
- `summary` — imperative mood, lowercase, no trailing period.

### Body

Separated from the title by a blank line. Brief, in English:

- **Why** the change was made.
- **What** changed, in a few lines.

### Trailers

Every commit ends with:

```
Session-Id: <session uuid>
Co-Authored-By: <model name> <noreply@anthropic.com>
```

- `Session-Id` is required: the id of the Claude Code session that produced
  the change. It is the UUID in the session's scratchpad path and transcript
  filename.
- `Co-Authored-By` is optional: when present, it names the model that
  co-authored the commit, exactly as given in the session's attribution
  instructions.

### Example

```
feat(skills/query): add metadata filters

Agents needed to narrow OKF searches by trust and lifecycle, not only by text.
Adds --type, --tag, --status, --stale and related flags, applied before the
text search.

Session-Id: 85ecceb1-1a51-4217-abfb-ed57d385b0b5
Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

## Pull requests

- Target `development` (or `master` only when releasing from `development`).
- Title follows the commit title format; description explains why and what.
- Follow [CODE_STANDARDS.md](CODE_STANDARDS.md).
- Add an entry to [CHANGELOG.md](CHANGELOG.md) under `Unreleased`.
- Do not delete the source branch when merging (no `--delete-branch`); branches
  are kept for traceability.
