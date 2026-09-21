# ruff: noqa: E501  (embedded HTML)
"""Link sessions to the work they produced: specs, tickets, branches and commits.

Everything here is a heuristic over references (paths, issue numbers, branches)
found in skill arguments and tool calls, never over free-text prompts. Only
titles and states of referenced files or issues are read, never their bodies.
"""

import html
import itertools
import json
import re
import subprocess
import time
from pathlib import Path

TAG_TO_TYPE = {
    "feat": "feature",
    "fix": "bugfix",
    "refactor": "refactor",
    "perf": "perf",
    "docs": "docs",
    "test": "test",
    "chore": "maintenance",
    "ci": "maintenance",
    "build": "maintenance",
    "style": "maintenance",
    "revert": "revert",
}
TYPE_LABEL = {
    "feature": "Feature",
    "bugfix": "Bug fix",
    "refactor": "Refactor",
    "perf": "Performance",
    "docs": "Docs",
    "test": "Test",
    "maintenance": "Maintenance",
    "revert": "Revert",
    "untyped": "No type signal",
}
TYPE_ORDER = list(TYPE_LABEL)
LABEL_TO_TYPE = {
    "bug": "bugfix",
    "fix": "bugfix",
    "enhancement": "feature",
    "feature": "feature",
    "documentation": "docs",
    "docs": "docs",
    "refactor": "refactor",
    "refactoring": "refactor",
    "performance": "perf",
    "test": "test",
    "tests": "test",
    "chore": "maintenance",
}
SKILL_TYPE = {"diagnosing-bugs": "bugfix", "improve-codebase-architecture": "refactor"}
COMMIT_TAG_RE = re.compile(r"^(\w+)(?:\(|:)")
PROTECTED_BRANCHES = {"master", "main", "development", "develop", "HEAD", ""}
STAGE_OF = {
    "grill-with-docs": "grill",
    "grill-me": "grill",
    "grilling": "grill",
    "wayfinder": "map",
    "to-spec": "spec",
    "to-tickets": "tickets",
    "triage": "triage",
    "implement": "implement",
    "tdd": "tdd",
    "code-review": "review",
    "diagnosing-bugs": "diagnose",
}
STAGE_ORDER = [
    "map",
    "grill",
    "spec",
    "tickets",
    "triage",
    "diagnose",
    "implement",
    "tdd",
    "review",
]

URL_RE = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+/(issues|pull)/(\d+)")
HASH_RE = re.compile(r"(?<![\w/&])#(\d+)\b")
GH_CMD_RE = re.compile(r"gh\s+(issue|pr)\s+(?:view|edit|comment|close)\s+#?(\d+)")
FILE_RE = re.compile(r"[\w./@-]+\.md\b")
NUM_RE = re.compile(r"(?<![\w.#/-])(\d{1,6})(?![\w.-])")
SLUG_RE = re.compile(r"\.scratch/([^/\s]+)/")


def stage_of(skill: str) -> str | None:
    return STAGE_OF.get(skill.lstrip("/"))


def extract_refs(text: str, root: Path | None = None) -> list[dict]:
    """References found in a skill's arguments or a tool command."""
    refs: list[dict] = []
    for kind, num in URL_RE.findall(text):
        refs.append({"kind": "gh", "type": "pr" if kind == "pull" else "issue", "number": int(num)})
    for typ, num in GH_CMD_RE.findall(text):
        refs.append({"kind": "gh", "type": "pr" if typ == "pr" else "issue", "number": int(num)})
    for num in HASH_RE.findall(text):
        refs.append({"kind": "gh", "type": "issue", "number": int(num)})
    for path in FILE_RE.findall(text):
        path = path.strip("./") if path.startswith("./") else path
        if ".scratch/" in path or (root and (root / path).is_file()):
            refs.append(
                {
                    "kind": "file",
                    "path": path[path.index(".scratch/") :] if ".scratch/" in path else path,
                }
            )
    return refs


def extract_command_refs(command: str) -> list[dict]:
    """Issue references in a shell command: only explicit `gh issue|pr view|edit|comment|close N`."""
    return [
        {"kind": "gh", "type": "pr" if t == "pr" else "issue", "number": int(n)}
        for t, n in GH_CMD_RE.findall(command)
    ]


def extract_bare_numbers(args: str) -> list[int]:
    """Numbers passed alone, like `/implement 42`. Their meaning depends on the tracker."""
    stripped = HASH_RE.sub(" ", URL_RE.sub(" ", args))
    stripped = FILE_RE.sub(" ", stripped)
    return [int(n) for n in NUM_RE.findall(stripped)]


def feature_of(path: str) -> str | None:
    m = SLUG_RE.search(path if path.startswith(".scratch/") else "/" + path)
    return m.group(1) if m else None


def detect_tracker(root: Path) -> str:
    """`local`, `github`, or `auto` when docs/agents/issue-tracker.md is absent or unclear."""
    try:
        head = (
            (root / "docs" / "agents" / "issue-tracker.md")
            .read_text(encoding="utf-8")[:300]
            .lower()
        )
    except OSError:
        return "auto"
    if "local markdown" in head:
        return "local"
    if "github" in head:
        return "github"
    return "auto"


# ---------- resolution (titles and states only) ----------


def resolve_file(root: Path, rel: str) -> dict:
    path = root / rel
    info = {"path": rel, "title": None, "status": None, "found": path.is_file()}
    if not info["found"]:
        return info
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
    except OSError:
        return info
    for line in lines:
        if line.startswith("# ") and not info["title"]:
            info["title"] = re.sub(r"^\d+:\s*", "", line[2:].strip())
        m = re.match(r"\**Status:?\**:?\s*\**\s*(.+)", line, re.I)
        if m and not info["status"]:
            info["status"] = m.group(1).strip("* ").lower()
    return info


def resolve_github(number: int, typ: str, cache: dict, offline: bool) -> dict:
    key = f"{typ}:{number}"
    entry = cache.get(key)
    if entry and time.time() - entry.get("at", 0) < 6 * 3600:
        return entry
    info = {
        "number": number,
        "type": typ,
        "title": None,
        "state": None,
        "url": None,
        "resolved": False,
    }
    if not offline:
        cmd = [
            "gh",
            "pr" if typ == "pr" else "issue",
            "view",
            str(number),
            "--json",
            "title,state,url",
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True).stdout
            data = json.loads(out)
            info.update(
                title=data.get("title"),
                state=(data.get("state") or "").lower(),
                url=data.get("url"),
                labels=[x.get("name", "") for x in data.get("labels") or []],
                resolved=True,
            )
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass
    if info["resolved"]:
        info["at"] = time.time()
        cache[key] = info
    return info


def load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_cache(path: Path, cache: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache))
    except OSError:
        pass


# ---------- commits ----------


def git_commits(root: Path) -> list[dict]:
    """Commits that carry a Session-Id trailer."""
    fmt = "%h%x1f%s%x1f%cI%x1f%(trailers:key=Session-Id,valueonly,separator=%x2c)%x1e"
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--all", f"--format={fmt}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    commits = []
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) == 4 and parts[3].strip():
            commits.append(
                {
                    "hash": parts[0],
                    "subject": parts[1],
                    "date": parts[2],
                    "sessions": [s.strip() for s in parts[3].split(",") if s.strip()],
                }
            )
    return commits


# ---------- grouping ----------


class _DSU:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _same_session(trailer: str, session_id: str) -> bool:
    """A Session-Id trailer may hold the full id or a prefix of at least 8 characters."""
    return len(trailer) >= 8 and (session_id.startswith(trailer) or trailer.startswith(session_id))


def session_keys(s: dict, tracker: str, root: Path) -> tuple[set[str], list[int]]:
    """Grouping keys for a session; also returns bare numbers that stayed unresolved."""
    keys: set[str] = set()
    unresolved: list[int] = []
    for ref in s["refs"]:
        if ref["kind"] == "gh":
            keys.add(f"gh:{ref['type']}:{ref['number']}")
        elif ref["kind"] == "file":
            slug = feature_of(ref["path"])
            keys.add(f"feature:{slug}" if slug else f"file:{ref['path']}")
    for num in s["bare_numbers"]:
        if tracker == "github":
            keys.add(f"gh:issue:{num}")
            continue
        matches = (
            list(root.glob(f".scratch/*/issues/{num:02d}-*.md"))
            if tracker in ("local", "auto")
            else []
        )
        if len(matches) == 1:
            keys.add(f"feature:{matches[0].parts[-3]}")
        else:
            unresolved.append(num)
    for slug in s["features"]:
        keys.add(f"feature:{slug}")
    branch = s.get("branch")
    if branch and branch not in PROTECTED_BRANCHES:
        keys.add(f"branch:{branch}")
    return keys, unresolved


def _attach_by_time(sessions, per_session, grouped, dsu, window_s: int = 24 * 3600) -> None:
    """Attach a reference-less grill or map session to the spec/tickets session right after it.

    Grilling happens before anything is written, so it has no reference of its own.
    The link is by time only and the session is flagged `attached`.
    """
    dated = sorted((s for s in sessions if s["start"]), key=lambda s: s["start"])
    for i, s in enumerate(dated):
        if (
            per_session[s["id"]]
            or not s["stages_seen"]
            or not set(s["stages_seen"]) <= {"grill", "map"}
        ):
            continue
        for nxt in dated[i + 1 :]:
            if (nxt["start"] - (s["end"] or s["start"])).total_seconds() > window_s:
                break
            if per_session[nxt["id"]] and {"spec", "tickets"} & set(nxt["stages_seen"]):
                s["attached"] = True
                grouped[dsu.find(sorted(per_session[nxt["id"]])[0])].append(s)
                break


def build_groups(
    sessions: list[dict], root: Path, tracker: str, offline: bool, cache_path: Path
) -> list[dict]:
    dsu = _DSU()
    per_session: dict[str, set[str]] = {}
    unresolved_by_session: dict[str, list[int]] = {}
    for s in sessions:
        keys, unresolved = session_keys(s, tracker, root)
        per_session[s["id"]] = keys
        unresolved_by_session[s["id"]] = unresolved
        ordered = sorted(keys)
        for k in ordered:
            dsu.find(k)
        for a, b in itertools.pairwise(ordered):
            dsu.union(a, b)

    grouped: dict[str, list[dict]] = {}
    for s in sessions:
        keys = per_session[s["id"]]
        if not keys:
            continue
        grouped.setdefault(dsu.find(sorted(keys)[0]), []).append(s)

    _attach_by_time(sessions, per_session, grouped, dsu)

    commits = git_commits(root)
    cache = load_cache(cache_path)
    groups = []
    for members in grouped.values():
        members.sort(key=lambda m: m["start"].timestamp() if m["start"] else 0)
        keys = set().union(*(per_session[m["id"]] for m in members))
        features = sorted(k.split(":", 1)[1] for k in keys if k.startswith("feature:"))
        branches = sorted(k.split(":", 1)[1] for k in keys if k.startswith("branch:"))
        files = [
            resolve_file(root, k.split(":", 1)[1]) for k in sorted(keys) if k.startswith("file:")
        ]
        for slug in features:
            for rel in [f".scratch/{slug}/spec.md", f".scratch/{slug}/map.md"]:
                if (root / rel).is_file():
                    files.append(resolve_file(root, rel))
            files.extend(
                resolve_file(root, str(p.relative_to(root)))
                for p in sorted((root / ".scratch" / slug / "issues").glob("*.md"))
            )
        gh = []
        for k in sorted(keys):
            if k.startswith("gh:"):
                _, typ, num = k.split(":")
                gh.append(resolve_github(int(num), typ, cache, offline))
        ids = [m["id"] for m in members]
        linked = [
            c for c in commits if any(_same_session(sid, i) for sid in c["sessions"] for i in ids)
        ]

        title = None
        for f in files:
            if f["path"].endswith(("spec.md", "map.md")) and f["title"]:
                title = f["title"]
                break
        title = (
            title
            or (features[0] if features else None)
            or next((g["title"] for g in gh if g["title"]), None)
        )
        title = (
            title
            or (f"#{gh[0]['number']}" if gh else None)
            or (branches[0] if branches else "work")
        )
        group = {
            "title": title,
            "features": features,
            "branches": branches,
            "files": files,
            "gh": gh,
            "sessions": members,
            "commits": linked,
            "unresolved": sorted({n for m in members for n in unresolved_by_session[m["id"]]}),
        }
        group["type"], group["type_source"] = classify_group(group)
        groups.append(group)
    save_cache(cache_path, cache)
    groups.sort(
        key=lambda g: g["sessions"][-1]["start"].timestamp() if g["sessions"][-1]["start"] else 0,
        reverse=True,
    )
    return groups


def classify_group(group: dict) -> tuple[str, str]:
    """Type of a piece of work and where the signal came from.

    Order of trust: commit tags (the commit convention), branch prefix, GitHub
    labels, the skill that opened the work. Without any of them: `untyped`.
    """
    tags: dict[str, int] = {}
    for c in group["commits"]:
        m = COMMIT_TAG_RE.match(c["subject"])
        if m and m.group(1) in TAG_TO_TYPE:
            t = TAG_TO_TYPE[m.group(1)]
            tags[t] = tags.get(t, 0) + 1
    if tags:
        best = max(tags.values())
        return min((t for t, n in tags.items() if n == best), key=TYPE_ORDER.index), "commit tags"
    for b in group["branches"]:
        prefix = b.split("/", 1)[0]
        if "/" in b and prefix in TAG_TO_TYPE:
            return TAG_TO_TYPE[prefix], "branch prefix"
    for g in group["gh"]:
        for label in g.get("labels") or []:
            if label.lower() in LABEL_TO_TYPE:
                return LABEL_TO_TYPE[label.lower()], "GitHub label"
    for m in group["sessions"]:
        for skill in m["skills"]:
            if skill.lstrip("/") in SKILL_TYPE:
                return SKILL_TYPE[skill.lstrip("/")], "skill"
    return "untyped", "none"


def esc(v) -> str:
    return html.escape(str(v))
