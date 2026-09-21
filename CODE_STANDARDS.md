# Code Standards

These standards apply to everything committed here. Sections marked *(stack)*
are placeholders: replace them with your project's language, formatter, linter
and test conventions when you start from this template.

## General

- Keep changes small and focused; one concern per commit.
- No secrets, tokens or personal data in the repo. Use `.env` (ignored) and
  document variables in `.env.example`.
- Every behavior change comes with a test, or a stated reason why not.

## Stack *(stack)*

- Language: Python ≥ 3.11, managed with `uv`.
- Lint and format: `ruff` (config in `pyproject.toml`), enforced by the `pre-commit` hook.
- Encoding: UTF-8, NFC-normalized, no BOM, no zero-width or bidi control characters
  (enforced by `scripts/check_unicode.py`).
- Test command: _to be defined_
- Directory layout: _to be defined_

## Documentation

- Every project `README.md` follows the section structure of
  [Best-README-Template](https://github.com/othneildrew/Best-README-Template), in
  this order: header block (title, one-line description, links), Table of Contents,
  About The Project (with Built With), Getting Started (Prerequisites,
  Installation), Usage, Roadmap, Contributing, License, Contact, Acknowledgments.
  Drop a section that does not apply instead of leaving it empty.
- Keep the `readme-top` anchor and a "back to top" link after each section.
- Start a new README from
  `.agents/skills/setup-project-harness/README.template.md`; `/setup-project-harness`
  does this for you.
- Do not add badges that point to a private repository (they render broken), and
  do not put personal e-mail addresses in the README; link the GitHub profile.
- Update the README in the same PR as the change it describes.

## Skills

- **Location:** the source lives in `.agents/skills/<name>/`. `.claude/skills/<name>`
  is a relative symlink to it (`../../.agents/skills/<name>`). Never duplicate a
  skill's files.
- **Entry point:** each skill has a `SKILL.md` with YAML frontmatter:
  - `name` — matches the directory name, kebab-case.
  - `description` — what it does **and** when to use it, including trigger
    phrases. This is what an agent reads to decide whether to invoke it.
  - `user-invocable` and, when it takes input, `argument-hint` listing every
    argument (`<required>`, `[optional]`).
  - `allowed-tools` — the minimum needed; read-only skills get no write tools.
- **Body:** imperative instructions for an agent, not prose for a human. State
  defaults, limits and failure behavior explicitly. Keep `SKILL.md` short; move
  long material to `reference/` and link it.
- **Supporting files:** scripts in `scripts/`, templates in `templates/`,
  references in `reference/`. Scripts must be deterministic and runnable from
  the CLI.
- **Third-party skills** tracked in `skills-lock.json` are not edited locally.
  Local skills are not listed there.

## Markdown

- One H1 per file. Headings in sentence case.
- Wrap prose at ~80 columns. Tables and code blocks are exempt.
- Fenced code blocks always declare a language (`bash`, `yaml`, `text`).
- Use relative links between files in the repo.

## Scripts

- Python scripts run with `uv run` and declare dependencies inline (PEP 723).
- Fail with a non-zero exit code and a clear message; never swallow errors.

## Language

- Code, comments, commits, PRs and documentation are written in English.

## Review checklist

- [ ] Follows the commit convention in [CONTRIBUTING.md](CONTRIBUTING.md)
- [ ] Skill frontmatter complete; `.claude/skills` symlink present
- [ ] No secrets, tokens or personal data
- [ ] [CHANGELOG.md](CHANGELOG.md) updated
