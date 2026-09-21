---
name: okf-query
description: >-
  Find documents in an Open Knowledge Format (OKF) bundle from a natural-language
  question and return the most relevant concepts, capped by a limit. Use when you
  need to look something up in a repository's `.wiki/` bundle ("what do we know
  about X", "where is Y documented", "which service owns Z") before answering or
  acting, or when the user asks to search, find, or query the knowledge bundle.
  Also filters by frontmatter metadata (type, tags, status, trust, staleness,
  path). Read-only; does not modify the bundle.
user-invocable: true
argument-hint: "[question] [--limit N] [--bundle <dir>] [--type T] [--tag T] [--status S] [--path P] [--generated-by A] [--verified-by A] [--resource R] [--source ID] [--stale|--fresh] [--unverified|--verified] [--include-deprecated]"
allowed-tools: Read Grep Glob
---

# Query an OKF bundle

Answer a natural-language question by locating the most relevant concepts in a
bundle. Read-only: to write knowledge back, use the `okf` skill in maintain mode.

## Arguments

`$ARGUMENTS` is the question plus optional flags:

- `--limit N` — maximum concepts to return. Default **5**, hard cap **20**. If N
  is missing, non-numeric, or below 1, use the default.
- `--bundle <dir>` — bundle root. Default `.wiki/` at the repository root; if that
  does not exist, look for a directory whose root `index.md` has `okf_version`.
  If no bundle is found, say so and stop.

### Metadata filters

Filters are exact frontmatter matches, combined with AND. A flag given more than
once (e.g. two `--tag`) is OR within that flag. Matching is case-insensitive.

| Flag | Matches |
|---|---|
| `--type T` | `type` equals T (e.g. `Service`, `Attested Computation`) |
| `--tag T` | `tags` contains T |
| `--status S` | `status` is `draft`, `stable`, or `deprecated` (absent counts as `stable`) |
| `--path P` | concept ID starts with P (e.g. `/services/`) |
| `--generated-by A` | `generated.by` contains A (e.g. `human:`, `process:`) |
| `--verified-by A` | any `verified[].by` contains A |
| `--resource R` | `resource` contains R |
| `--source ID` | any `sources[].id` or `sources[].resource` contains ID |
| `--stale` / `--fresh` | `stale_after` is already past / not past or absent |
| `--verified` / `--unverified` | has / lacks a `verified` entry |
| `--include-deprecated` | keep `deprecated` concepts (excluded by default) |

Strip all flags; everything left is the question. **The question is optional
when at least one filter is given** — then list every concept passing the
filters (up to the limit), ordered by `generated.at`, newest first. With neither
question nor filters, ask for one and stop. An unknown flag or a filter that
matches nothing is reported, not silently ignored.

## Procedure

1. **Start from the root `index.md`** for a map of directories and concepts.
2. **Turn the question into search terms:** keep nouns and identifiers, add
   obvious synonyms and singular/plural forms. Drop filler words. Questions may
   be in any language; search in the question's language and, if the bundle is
   in another, the translated terms.
3. **Filter first, when filters were given:** Grep the frontmatter fields
   (`^type:`, `^tags:`, `^status:`, …) to narrow the candidate set, then run the
   text search only inside it. Confirm multi-line fields (`generated`,
   `verified`, `sources`) by reading the frontmatter.
   **Search** the bundle's `.md` files with Grep (case-insensitive), skipping
   `index.md` and `log.md`. Match in this order of signal:
   1. filename / concept ID (Glob)
   2. frontmatter `title`, `description`, `tags`
   3. headings
   4. body text
4. **Rank** candidates: more distinct terms matched beats more repeats; a hit in
   a higher-signal position beats a lower one. Follow links from the best hits
   only when they plainly answer the question.
5. **Read the top candidates** (frontmatter plus enough body to confirm) before
   listing them. Drop those that turn out to be irrelevant.
6. **Weigh trust** (spec §5): `status: deprecated` — exclude unless
   `--include-deprecated`, `--status deprecated`, or nothing else matches; then
   flag it. `status: draft`, a past `stale_after`, or no `verified`
   entry — keep, but flag "check before relying".
7. **Truncate to `--limit`.** If more matched, say how many were left out.

## Output

One entry per concept, best first:

```
1. /services/auth-api.md — Auth API  [type: Service]
   Why: <one line tying it to the question>
   Flags: draft | stale since 2026-01-01 | unverified   (omit if none)
```

Then a short answer to the question drawn only from what you read, citing concept
paths. If nothing relevant was found, say so plainly and list the terms tried —
do not fill the list with weak matches or answer from memory.
