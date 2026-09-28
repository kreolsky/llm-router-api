#!/usr/bin/env python3
"""Cyrillic gate — no untranslated prose in src/ or in release notes.

The codebase's working language for code comments and docstrings is English,
and release notes (docs/release/) are always written in English. A Cyrillic line in src/ is either an
untranslated comment (drift) or a log message meant for operators that was
never localized for the repo's readers — either way it belongs elsewhere.

Finds any line containing a Cyrillic codepoint (U+0400–U+04FF) in src/**.py
or docs/release/*.md and fails listing file:line.

Usage:
  cyrillic-src-gate.py            # exit 1 when any Cyrillic line is found
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
SCAN_GLOBS = (("src", "**/*.py"), ("docs/release", "*.md"))


def cyrillic_lines() -> list[str]:
    hits: list[str] = []
    paths = [p for base, pattern in SCAN_GLOBS for p in sorted((ROOT / base).glob(pattern))]
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            if any("\u0400" <= ch <= "\u04FF" for ch in line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    return hits


def main() -> int:
    hits = cyrillic_lines()
    if hits:
        print("Cyrillic found in src/ or docs/release/ — translate it to English:")
        for hit in hits:
            print(f"  {hit}")
        return 1
    print("OK — no Cyrillic in src/ or docs/release/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
