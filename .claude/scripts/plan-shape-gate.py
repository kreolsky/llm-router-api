#!/usr/bin/env python3
"""Plan-shape gate — a plan file has ONE fixed shape, and it is small.

Checks only plans NEW or MODIFIED in this commit (`plans/*.md`, archive/
excluded). Pre-existing plans are history and are never rewritten — a
count baseline would be the wrong instrument here, because a plan is written
once and then read, not grown.

What it enforces, and why each one is a gate rather than prose:

* Section whitelist. Measured across the 40 newest plans: ~20 distinct H2 types,
  with the single "what we are NOT doing" section appearing under five different
  names. Structure was re-invented per plan because nothing held it, and
  re-inventing structure is where design prose gets written instead of steps.
* Line cap. Over the cap the task is too big to plan — it gets SPLIT, not
  planned more densely. The gate stops at 150 while workflow.md asks for 120: the
  30-line gap is deliberate slack, so a plan that lands slightly over gets split
  on judgement rather than shaved. Why: a research plan finished at 124 lines and
  three consecutive edits went to squeezing out 4 lines of real findings — pure
  formalism, no plan got smaller in any sense that mattered. 120 is the target
  you write to; 150 is where the size is genuinely the problem.
* No decision IDs (`D7`, `F0`, `R3`). Needing a cross-reference registry is
  itself the signal that the document outgrew being an instruction.

The banned sections are all one genre: a record of the thinking (`Intent drift`,
`Context`, `Goal`, `Session bootstrap`, `Discovery already done`). workflow.md
already bans dead design in prose; a 344-line plan carrying five obituaries of
rejected designs was written days after that rule landed, which is what made
this a gate.

Usage:
  plan-shape-gate.py              # check plans changed vs HEAD (+ untracked)
  plan-shape-gate.py PATH ...     # check the named files (used by save-plan.py)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
PLAN_DIR = "plans/"
# Target is 120 (workflow.md); the gate fires at 150 so near-misses are split on
# judgement, not shaved line-by-line to satisfy the check.
MAX_LINES = 150

REQUIRED = ("Decisions", "Risks", "Order", "Not doing")
# Validation is OPTIONAL, not required: Phase 4 exempts diffs with no runtime surface
# (tests/docs/config only). Requiring it there would manufacture an empty section, which
# is how a whitelist starts growing filler. 41% of the 470 pre-existing plans carried this
# section under two names (`Validation`, `Verification`) — the concept earned its slot.
OPTIONAL = ("Validation", "Progress")
ALLOWED = REQUIRED + OPTIONAL

H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
# A citation into the tree: `backend/x.py:120`, `pi-driver/src/server.ts:731`, `a.py:12-34`.
CITE_RE = re.compile(r"`?([\w./\-]+\.(?:py|md|sh|json|yml|yaml)):(\d+)(?:-(\d+))?`?")
H1_RE = re.compile(r"^#\s+\S", re.M)
# Plans are named `<epoch-ms>-<slug>.md` (save-plan.py). The timestamp is the only
# ordering the directory has — a plan named by slug alone cannot be placed in time,
# and `ls -t` breaks the moment a file is copied or checked out.
TS_NAME_RE = re.compile(r"^\d{13}-[a-z0-9-]+\.md$")
# A decision ID used as a label: line-leading, optionally bulleted/bolded.
DECISION_ID_RE = re.compile(r"^\s*(?:[-*]\s*)?\*{0,2}([DFR]\d{1,2})\b")
# Cyrillic anywhere in the file. Plans are English-only (workflow.md `## Plans`) —
# the request's language does not carry into the artifact, because the plan is read
# by an executor and by the tree's own markers, both of which are English.
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def changed_plans() -> list[Path]:
    """Plans added or modified vs HEAD, plus untracked ones."""
    out: set[str] = set()
    for cmd in (
        ["git", "diff", "HEAD", "--name-only", "--diff-filter=ACMR"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        out.update(line for line in res.stdout.splitlines() if line.strip())
    return [
        ROOT / p
        for p in sorted(out)
        if re.match(PLAN_DIR, p) and p.endswith(".md")
        and "/archive/" not in p and "/superseded/" not in p
    ]


def check_citations(text: str) -> list[str]:
    """`## Decisions` must cite the tree, and every citation it makes must resolve.

    Why this and not more prose: one intent drift cost a rewrite because a plan proposed
    listing an always-core tool under a skill's `tools:` — which READS as granting access
    while `computeCoreTools` builds core by subtracting every pack, so the entry withdraws
    the tool instead. The plan became correct the moment someone opened the file. A
    citation cannot be written without opening it, and a fabricated one fails here.

    The gate cannot tell WHICH decision needed a citation, so it asks for one in the
    section and verifies all of them. That is the checkable half; judgement stays human.
    """
    body = re.split(r"^##\s+", text, flags=re.M)
    section = next((s for s in body if s.startswith("Decisions")), None)
    if section is None:
        return []  # a missing section is already reported by the whitelist check

    cites = CITE_RE.findall(section)
    if not cites:
        return [
            "`## Decisions` cites nothing — every decision touching existing behaviour "
            "needs a `file:line` that resolves (open the file, don't infer the contract)"
        ]

    problems: list[str] = []
    for rel, start, end in cites:
        target = ROOT / rel
        if not target.is_file():
            problems.append(f"citation `{rel}:{start}` — no such file")
            continue
        try:
            total = len(target.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError as exc:
            problems.append(f"citation `{rel}:{start}` — unreadable ({exc})")
            continue
        for n in (start, end):
            if n and int(n) > total:
                problems.append(
                    f"citation `{rel}:{n}` — file has {total} lines"
                )
    return problems


def check(path: Path) -> list[str]:
    """Return violation strings for one plan file (empty = clean)."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return [f"unreadable: {exc}"]

    problems: list[str] = []
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        problems.append(
            f"{len(lines)} lines > {MAX_LINES} — the task is too big to plan; split it"
        )
    if not H1_RE.search(text):
        problems.append("no `# <title>` heading")
    if not TS_NAME_RE.match(path.name):
        problems.append(
            f"filename `{path.name}` is not `<epoch-ms>-<slug>.md` — "
            "plans are named by save-plan.py; rename it to keep the directory ordered"
        )

    found = H2_RE.findall(text)
    for name in found:
        if name not in ALLOWED:
            problems.append(f"section `## {name}` is not in the whitelist")
    for name in REQUIRED:
        if name not in found:
            problems.append(f"missing required section `## {name}`")

    cyrillic = [
        f"{n}: {line.strip()[:70]}"
        for n, line in enumerate(lines, 1)
        if CYRILLIC_RE.search(line)
    ]
    if cyrillic:
        problems.append(
            f"Cyrillic on {len(cyrillic)} line(s) — plans are English-only, every "
            f"heading and body line, whatever the language of the request "
            f"(first: {cyrillic[0]})"
        )

    problems += check_citations(text)

    seen_ids = sorted(
        {m.group(1) for line in lines if (m := DECISION_ID_RE.match(line))}
    )
    if seen_ids:
        problems.append(
            f"decision IDs used as labels ({', '.join(seen_ids)}) — "
            "a plan needing a cross-reference registry is too big"
        )
    return problems


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    targets = [Path(a).resolve() for a in args] if args else changed_plans()
    if not targets:
        print("plan-shape: no new or modified plans.")
        return 0

    failed = 0
    for path in targets:
        problems = check(path)
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        if problems:
            failed += 1
            print(f"FAIL {rel}")
            for p in problems:
                print(f"       - {p}")
        else:
            print(f"ok   {rel}")

    if failed:
        print(
            f"\n{failed} plan(s) off-shape. Allowed sections: "
            + ", ".join(f"## {s}" for s in ALLOWED)
            + f"; max {MAX_LINES} lines."
        )
        print("Understanding changed ⇒ REWRITE the plan, don't append to it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
