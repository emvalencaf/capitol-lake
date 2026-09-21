#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///
"""Fail if any given file is not clean, NFC-normalized UTF-8 text.

Rejects: invalid UTF-8, a leading BOM, NUL, U+FFFD, zero-width and bidi control
characters, and text that is not NFC-normalized. Binary files are skipped.
Usage: check_unicode.py FILE...
"""

import sys
import unicodedata
from pathlib import Path

FORBIDDEN = {
    0x0000: "NUL",
    0xFFFD: "replacement character (U+FFFD)",
    0x200B: "zero-width space",
    0x200C: "zero-width non-joiner",
    0x200D: "zero-width joiner",
    0x2060: "word joiner",
    **{c: "bidi control" for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))},
}


def check(path: Path) -> list[str]:
    if path.is_symlink() or not path.is_file():
        return []  # symlinks (e.g. skill links) and directories have no text
    raw = path.read_bytes()
    if b"\x00" in raw[:8192] and not raw.startswith(b"\xef\xbb\xbf"):
        return []  # binary file
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{path}: invalid UTF-8 at byte {exc.start}"]
    errors = []
    if text.startswith("\ufeff"):
        errors.append(f"{path}:1:1: forbidden BOM")
    for lineno, line in enumerate(text.splitlines(), 1):
        for col, ch in enumerate(line, 1):
            name = FORBIDDEN.get(ord(ch))
            if name:
                errors.append(f"{path}:{lineno}:{col}: forbidden {name}")
    if unicodedata.normalize("NFC", text) != text:
        errors.append(f"{path}: not NFC-normalized")
    return errors


def main(files: list[str]) -> int:
    errors = [e for f in files for e in check(Path(f))]
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
