#!/usr/bin/env python3
"""Release pre-flight: the read-only checks the release skill runs before tagging.

Each check prints STOP (blocks the release), WARN (needs a line in the release note)
or ok. The version LEVEL, the note text and the push stay the operator's call — this
only gathers the evidence they are decided from, against the repo, never memory.

Usage: release-audit.py [--fetch]      (--fetch runs `git fetch origin --tags` first)
Exit 1 if any check is STOP.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTES = ROOT / "docs" / "release"
SETTINGS_FILE = "src/core/config_manager.py"
REBUILD_FILES = ("requirements.txt", "Dockerfile")
SUBJECT_TYPE = re.compile(r"^([a-z]+)(\([^)]*\))?(!)?:")
SETTINGS_FIELD = re.compile(r"^\s{4}([a-z_]+): [a-z]+ = ", re.M)

stops = 0


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return r.stdout.strip()


def report(level: str, title: str, body: str = "") -> None:
    global stops
    stops += level == "stop"
    print(f"{ {'stop': 'STOP', 'warn': 'WARN', 'ok': '  ok'}[level] }  {title}")
    for line in body.splitlines():
        print(f"        {line}")


def last_tag() -> str | None:
    """Newest v-tag reachable from origin/dev; None before the first release."""
    return git("describe", "--tags", "--abbrev=0", "--match", "v*", "origin/dev") or None


def check_fast_forward() -> None:
    extra = git("log", "origin/dev..origin/main", "--oneline")
    if extra:
        return report("stop", "fast-forward impossible — origin/main has commits origin/dev lacks",
                      extra + "\nHalt and ask the operator. Never --force.")
    n = len(git("log", "origin/main..origin/dev", "--oneline").splitlines())
    report("ok", f"fast-forward clean — {n} commits ahead of main "
                 f"(dev={git('rev-parse', '--short', 'origin/dev')})")


def check_local_in_sync() -> None:
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/dev"):
        return report("stop", "local HEAD is not origin/dev — push dev (or pull) before releasing")
    report("ok", "local HEAD == origin/dev")


def check_commit_types(since: str | None) -> None:
    rev = f"{since}..origin/dev" if since else "origin/dev"
    counts: dict[str, int] = {}
    breaking = False
    for sha in git("rev-list", "--no-merges", rev).splitlines():
        subject, _, body = git("show", "-s", "--format=%s%n%b", sha).partition("\n")
        m = SUBJECT_TYPE.match(subject)
        kind = m.group(1) if m else "other"
        counts[kind] = counts.get(kind, 0) + 1
        breaking |= bool(m and m.group(3)) or "BREAKING CHANGE" in body
    level = "major" if breaking else "minor" if counts.get("feat") else "patch"
    summary = ", ".join(f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    report("ok", f"since {since or 'the first commit'}: {summary} → recommended level: {level}"
                 + (" (BREAKING CHANGE present)" if breaking else ""))


def check_rebuild(since: str | None) -> None:
    if not since:
        return report("ok", "first release — no rebuild diff to compute")
    changed = git("diff", "--name-only", f"{since}..origin/dev", "--", *REBUILD_FILES)
    if changed:
        return report("warn", "next deploy is a full rebuild — changed since the last tag:", changed)
    report("ok", "requirements.txt / Dockerfile unchanged — deploy is a restart")


def settings_fields(source: str) -> set[str]:
    """Field names of the `Settings` dataclass — each one is an upper-cased env var."""
    body = source.partition("class Settings")[2]
    body = re.split(r"^(?:class|def) ", body, maxsplit=1, flags=re.M)[0]
    return set(SETTINGS_FIELD.findall(body))


def check_new_settings(since: str | None) -> None:
    if not since:
        return report("ok", "first release — every Settings field is documented in README")
    old = settings_fields(git("show", f"{since}:{SETTINGS_FILE}"))
    new = settings_fields(git("show", f"origin/dev:{SETTINGS_FILE}"))
    added = sorted(new - old)
    if added:
        return report("warn", "new env vars since the last tag — name each in the note:",
                      "\n".join(name.upper() for name in added))
    report("ok", "no new env vars")


def check_newest_note() -> None:
    notes = sorted(NOTES.glob("release-*.md")) if NOTES.is_dir() else []
    if not notes:
        return report("warn", "no release note yet — write docs/release/release-YYYY-MM-DD-vX.Y.Z.md")
    report("ok", f"newest note: {notes[-1].name} — {notes[-1].read_text(encoding='utf-8').splitlines()[0]}")


def main() -> int:
    if "--fetch" in sys.argv:
        subprocess.run(["git", "-C", str(ROOT), "fetch", "origin", "--tags", "--quiet"], check=True)
    dirty = git("status", "--porcelain", "--untracked-files=no")
    report("warn" if dirty else "ok", "tracked working-tree changes present (not part of the release)"
           if dirty else "no tracked working-tree changes", dirty)
    since = last_tag()
    print(f"        last tag: {since or 'none (first release)'}")
    check_fast_forward()
    check_local_in_sync()
    check_commit_types(since)
    check_rebuild(since)
    check_new_settings(since)
    check_newest_note()
    return 1 if stops else 0


if __name__ == "__main__":
    sys.exit(main())
