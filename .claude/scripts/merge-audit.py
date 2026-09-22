#!/usr/bin/env python3
"""Pre-merge audit — read-only. Reports STOPs, then hands the decision back.

The branch, not the commit, is the unit that owes proof (`workflow.md` → *inside an L
branch a commit is a step, not a release*). Nothing else checks that: the review-gate
hook lets intermediate commits through by design, so if the merge does not ask for the
branch-level review, no one ever does.

The review sentinel is `<git-dir>/review-ok`, written by `/review` with the SHA it
reviewed. Comparing it to HEAD is what makes the check mean "this tip was reviewed"
rather than "a review happened here once" — a commit added after the review invalidates
it, which is exactly the case a bare marker file would wave through.

Exit 1 on any STOP. Consent is not observable from here: the caller still halts and asks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def git(*args: str) -> str:
    """Run a git command and return stripped stdout ('' on failure)."""
    res = subprocess.run(["git", *args], capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def check_branch() -> list[str]:
    """A merge is run FROM a feature branch, never from a base branch."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    print(f"branch:      {branch}")
    if branch in ("main", "dev"):
        return [f"on `{branch}` — a merge is run from the feature branch, not the base"]
    return []


def check_review() -> list[str]:
    """The branch tip must be the SHA `/review` recorded."""
    sentinel = Path(git("rev-parse", "--git-dir")) / "review-ok"
    head = git("rev-parse", "HEAD")
    if not sentinel.is_file():
        return ["no `/review` recorded for this branch — it is the branch's only review gate"]
    reviewed = sentinel.read_text(encoding="utf-8", errors="ignore").strip()
    if reviewed != head:
        return [
            f"the reviewed commit ({reviewed[:8] or 'unknown'}) is not the branch tip "
            f"({head[:8]}) — commits landed after the review; re-run `/review`"
        ]
    print(f"review:      ok ({head[:8]})")
    return []


def check_freshness() -> list[str]:
    """A branch behind origin/dev is rebased before it is merged, never after."""
    subprocess.run(["git", "fetch", "--quiet"], capture_output=True, text=True)
    behind = git("log", "HEAD..origin/dev", "--oneline")
    if behind:
        n = len(behind.splitlines())
        return [f"behind origin/dev by {n} commit(s) — rebase onto origin/dev first"]
    print("freshness:   up to date with origin/dev")
    return []


def report_diff() -> None:
    """What this merge would actually carry."""
    print(f"\ncommits dev..HEAD:\n{git('log', 'dev..HEAD', '--oneline') or '  (none)'}")
    print(f"\n{git('diff', 'dev', 'HEAD', '--stat') or '  (no diff)'}")


def main() -> int:
    print("━━━ pre-merge audit ━━━")
    stops = check_branch() + check_review() + check_freshness()

    if dirty := git("status", "--short"):
        print(
            "\nWARN unclean working tree — foreign in-flight edits are legitimate and stay\n"
            "     untouched (`git-strategy.md`); never sweep them into this merge:\n"
            + "\n".join(f"     {line}" for line in dirty.splitlines())
        )

    report_diff()

    if stops:
        print("\n━━━ STOP ━━━")
        for s in stops:
            print(f"  - {s}")
        return 1
    print("\nNo STOPs. Halt and ask the user for explicit confirmation before merging.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
