#!/usr/bin/env python3
"""Generate lessons/INDEX.md from lesson frontmatter (category/systems), grouped by category.

Usage:
  lessons-index.py --write   regenerate lessons/INDEX.md
  lessons-index.py --check   advisory: exit 1 if INDEX.md is stale or a lesson lacks category
                             (NOT wired into CI — used by /retro and /reality-audit)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LESSONS = ROOT / "lessons"
INDEX = LESSONS / "INDEX.md"

# Taxonomy: category -> one-line meaning. New categories are added here AND in retro/SKILL.md.
CATEGORIES = {
    "gating-condition": "feature \"missing/broken\" was a mode/permission/flag gate",
    "stale-runtime": "running code != edited code (Docker mount, rebuild, cache)",
    "contract-drift": "doc/marker/protocol said X, code did Y",
    "race-timing": "async/WS/store ordering, focus/mount races",
    "class-not-symptom": "repeated symptom patched member-by-member instead of normalizing the class",
    "diagnosis-method": "a reusable way to observe/reproduce before fixing",
    "api-mismatch": "hallucinated or version-mismatched API",
    "platform-mechanics": "non-obvious platform behavior (CM6/CSS/React/driver/queue) that defied intuition",
    "silent-failure": "an error was swallowed; user saw stale/blank instead of an error",
    "migration-schema": "DB schema/migration/backfill traps",
    "agent-adjudication": "a decision was left to the model that the server can make deterministically",
    "process-workflow": "how we work: planning, review, sizing, questioning",
    "tooling-gap": "missing harness/test/CI capability that caused blind work",
}

FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse(path: Path) -> tuple[str, list[str], str]:
    """Return (category, systems, title). Empty category if no frontmatter."""
    text = path.read_text()
    category, systems = "", []
    m = FM_RE.match(text)
    body = text[m.end():] if m else text
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("category:"):
                category = line.split(":", 1)[1].strip()
            elif line.startswith("systems:"):
                systems = [s.strip() for s in line.split(":", 1)[1].strip().strip("[]").split(",") if s.strip()]
    title = next((l.lstrip("# ").strip() for l in body.splitlines() if l.startswith("# ")), path.stem)
    # Strip a leading "YYYY-MM-DD — " duplicate of the filename date.
    title = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[—-]\s*", "", title)
    return category, systems, title


def render() -> tuple[str, list[str]]:
    """Return (index markdown, problems)."""
    problems: list[str] = []
    groups: dict[str, list[str]] = {c: [] for c in CATEGORIES}
    for f in sorted(LESSONS.glob("*.md")):
        if f.name == "INDEX.md":
            continue
        category, systems, title = parse(f)
        if not category:
            problems.append(f"{f.name}: no category frontmatter")
            continue
        if category not in CATEGORIES:
            problems.append(f"{f.name}: unknown category '{category}' (add it to lessons-index.py + retro skill)")
            continue
        sys_part = f" `[{', '.join(systems)}]`" if systems else ""
        groups[category].append(f"- {f.stem[:10]} — [{title}]({f.name}){sys_part}")
    lines = [
        "# Lessons Index (generated — do not edit; `.claude/scripts/lessons-index.py --write`)",
        "",
        "One line per lesson, grouped by knowledge category. Debugging intake: check the",
        "category matching the symptom class before investigating.",
        "",
    ]
    for cat, meaning in CATEGORIES.items():
        entries = groups[cat]
        if not entries:
            continue
        lines.append(f"## {cat} ({len(entries)}) — {meaning}")
        lines.append("")
        lines.extend(entries)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", problems


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    content, problems = render()
    for p in problems:
        print(f"PROBLEM: {p}", file=sys.stderr)
    if mode == "--write":
        INDEX.write_text(content)
        print(f"wrote {INDEX.relative_to(ROOT)}")
        sys.exit(1 if problems else 0)
    stale = not INDEX.exists() or INDEX.read_text() != content
    if stale:
        print("INDEX.md is stale — run lessons-index.py --write", file=sys.stderr)
    sys.exit(1 if (problems or stale) else 0)


if __name__ == "__main__":
    main()
