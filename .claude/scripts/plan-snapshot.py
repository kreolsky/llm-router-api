#!/usr/bin/env python3
"""PreToolUse(Write|Edit) hook: keep the version of a plan that is about to be replaced.

`workflow.md` says understanding changed ⇒ delete the plan and write it again. That
rule works — but each firing destroys the only copy of the draft that went wrong, and
the monstrous drafts are the ones never committed. A three-hour post-mortem of one
intent drift ran on memory alone because `git log` held exactly one version of the
plan: the final, correct one.

So: before a plan file is overwritten, its current content is copied to
`plans/superseded/<name>.<epoch>.md`. Costs the author nothing, changes no
rule, and makes the NEXT drift diagnosable from a diff instead of recollection.

Never blocks: any failure is reported and the write proceeds. Snapshots are skipped
when the content is unchanged, and pruned after 30 days.
"""

import json
import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
SUPERSEDED = ROOT / "plans" / "superseded"
KEEP_DAYS = 30


def target_path() -> pathlib.Path | None:
    """The file this Write/Edit is about to touch, from env or the hook payload."""
    raw = os.environ.get("CLAUDE_FILE_PATH", "")
    if not raw:
        try:
            data = json.loads(sys.stdin.read() or "{}")
        except (json.JSONDecodeError, OSError):
            return None
        for key in ("tool_input", "toolInput", "input"):
            block = data.get(key)
            if isinstance(block, dict):
                raw = block.get("file_path") or block.get("path") or ""
                if raw:
                    break
        raw = raw or data.get("file_path", "")
    return pathlib.Path(raw) if raw else None


def prune() -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for p in SUPERSEDED.glob("*.md"):
        if p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)


def main() -> int:
    path = target_path()
    if not path:
        return 0
    parts = path.parts
    if "plans" not in parts or path.suffix != ".md":
        return 0
    if "superseded" in parts or "archive" in parts:
        return 0
    if not path.is_file():
        return 0  # a brand-new plan supersedes nothing

    try:
        SUPERSEDED.mkdir(parents=True, exist_ok=True)
        current = path.read_bytes()
        # Skip a no-op rewrite: the newest snapshot already holds this content.
        existing = sorted(SUPERSEDED.glob(f"{path.stem}.*.md"))
        if existing and existing[-1].read_bytes() == current:
            return 0
        dest = SUPERSEDED / f"{path.stem}.{int(time.time())}.md"
        shutil.copy2(path, dest)
        prune()
        print(json.dumps({"systemMessage":
                          f"Superseded plan kept → {dest.relative_to(ROOT)}"}))
    except OSError as exc:
        print(json.dumps({"systemMessage": f"plan-snapshot failed ({exc}) — write proceeds."}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
