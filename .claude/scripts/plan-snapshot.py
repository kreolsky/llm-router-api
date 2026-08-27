#!/usr/bin/env python3
"""PreToolUse(Write|Edit|Bash) hook: keep the version of a plan about to be replaced.

`workflow.md` says understanding changed ⇒ delete the plan and write it again. That
rule works — but each firing destroys the only copy of the draft that went wrong, and
the monstrous drafts are the ones never committed. A three-hour post-mortem of one
intent drift ran on memory alone because `git log` held exactly one version of the
plan: the final, correct one.

So: before a plan file is overwritten, its current content is copied to
`plans/superseded/<name>.<epoch>.md`. Costs the author nothing, changes no
rule, and makes the NEXT drift diagnosable from a diff instead of recollection.

Bash is matched too, not only Write|Edit: a plan edited with `sed -i`, a heredoc or
`>` never reaches the Write tool, so the hook silently did nothing for every such edit
and `plans/superseded/` stayed empty while plans were being patched in place.

Never blocks: any failure is reported and the write proceeds. Snapshots are skipped
when the content is unchanged, and pruned after 30 days.
"""

import json
import os
import pathlib
import re
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
SUPERSEDED = ROOT / "plans" / "superseded"
KEEP_DAYS = 30


# A plans/*.md path as it appears inside a shell command line.
PLAN_IN_CMD_RE = re.compile(r"[\w./\-]*plans/[\w.\-]+\.md")
# Write intent. A command that only READS a plan (`cat`, `grep`, `head`) must not burn a
# snapshot slot, so the path alone is not enough — something must be about to modify it.
WRITE_INTENT_RE = re.compile(
    r">>?|\bsed\s+-i|\btee\b|\bmv\b|\bcp\b|\brm\b|\btruncate\b|"
    r"\bpython3?\b|\bperl\b|\bawk\b"
)


def targets() -> list[pathlib.Path]:
    """The plan files this tool call is about to touch, from env or the hook payload."""
    raw = os.environ.get("CLAUDE_FILE_PATH", "")
    if raw:
        return [pathlib.Path(raw)]
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError):
        return []
    block: dict = {}
    for key in ("tool_input", "toolInput", "input"):
        found = data.get(key)
        if isinstance(found, dict):
            block = found
            break
    raw = block.get("file_path") or block.get("path") or data.get("file_path", "")
    if raw:
        return [pathlib.Path(raw)]
    command = block.get("command") or data.get("command") or ""
    if not command or not WRITE_INTENT_RE.search(command):
        return []
    return [pathlib.Path(m) for m in dict.fromkeys(PLAN_IN_CMD_RE.findall(command))]


def prune() -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for p in SUPERSEDED.glob("*.md"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)


def snapshot(path: pathlib.Path) -> str | None:
    """Copy `path` aside if it is a live plan with content not already kept."""
    parts = path.parts
    if "plans" not in parts or path.suffix != ".md":
        return None
    if "superseded" in parts or "archive" in parts:
        return None
    if not path.is_file():
        return None  # a brand-new plan supersedes nothing

    try:
        SUPERSEDED.mkdir(parents=True, exist_ok=True)
        current = path.read_bytes()
        # Skip a no-op rewrite: the newest snapshot already holds this content.
        existing = sorted(SUPERSEDED.glob(f"{path.stem}.*.md"))
        if existing and existing[-1].read_bytes() == current:
            return None
        dest = SUPERSEDED / f"{path.stem}.{int(time.time())}.md"
        shutil.copy2(path, dest)
        prune()
        return str(dest.relative_to(ROOT))
    except OSError as exc:
        return f"{path.name}: snapshot failed ({exc}) — the write proceeds"


def main() -> int:
    kept = [msg for path in targets() if (msg := snapshot(path))]
    if kept:
        print(json.dumps({"systemMessage": "plan-snapshot: " + ", ".join(kept)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
