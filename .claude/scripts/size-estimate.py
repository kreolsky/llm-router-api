#!/usr/bin/env python3
"""Two-axis sizer for this gateway (see .claude/rules/workflow.md → sizing).

Two INDEPENDENT axes, because they answer different questions:

  * Commits       -> how much PROCESS (S / M / L phases). Read from the plan's
                     `## Order`, or from the diff's judgement at review time.
  * Entanglement  -> how much PROOF (test breadth + model). It is what must be held
                     at once to not break the change, and it does NOT decompose:
                     a one-file edit sitting on an `INVARIANT:` at the
                     auth -> service -> provider -> stream boundary is high-e.

FILE COUNT IS NOT AN AXIS. It measures the process (a fix + its test + its plan is
three files) rather than the work, which is why the old "≤3 files" rule mislabelled
every tested change.

Signals are read ONLY from production `+` lines (`src/`), so prose about an invariant
never inflates the score; an `INVARIANT:` pinned IN code does count — decision-pinning
is real entanglement.

Usage:
  size-estimate.py                          # working tree vs HEAD (review-time check)
  size-estimate.py <commit>                 # a single commit
  size-estimate.py --plan <file> [--append] # draft estimate from a plan's text
"""
from __future__ import annotations

import re
import subprocess
import sys

# Process-boundary buckets. A change touching several of them crosses boundaries the
# request travels through (middleware -> auth -> service -> provider -> upstream), and
# every edge is a desync/lifecycle risk.
BOUNDARIES = {
    "provider": re.compile(r"src/providers/"),
    "service": re.compile(r"src/services/"),
    "stream": re.compile(r"(stream_processor|open_provider_stream|StreamingResponse|sse)", re.I),
    "auth": re.compile(r"(src/core/auth|user_keys|access|security)", re.I),
    "config": re.compile(r"(config_manager|config/.*\.yaml|providers\.yaml|models\.yaml)"),
    "usage_db": re.compile(r"usage_db|src/api/routes/stat"),
    "capabilities": re.compile(r"model_capabilities|model_info"),
    "http_pool": re.compile(r"(AsyncClient|aclose|httpx|Semaphore|max_concurrent)"),
}
INVARIANT = re.compile(r"^\+.*\bINVARIANT(\([a-z-]+\))?:", re.M)
CONCURRENCY = re.compile(r"^\+.*\b(asyncio\.|await |async def|Semaphore|Lock\(|gather)", re.M)
ROUTE = re.compile(r"^\+.*@(app|router)\.(get|post|put|delete|patch)", re.M)
PROD = re.compile(r"^src/")


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True).stdout


def classify(e: int) -> tuple[str, str, str]:
    """(label, model, test regime) for an entanglement score."""
    if e <= 2:
        return "low", "Haiku", "targeted tests over what this diff can break + adjacent, --tb=line"
    if e <= 6:
        return "medium", "Sonnet", "full unit suite (tests/unit) + the api tests the diff touches"
    return "high", "Opus", "full suite tests/ AND a repeat run (races, stream ordering, pool lifecycle)"


def score(files: list[str], diff: str) -> tuple[int, list[str]]:
    prod_files = [f for f in files if PROD.match(f)]
    added = "\n".join(
        ln for ln in diff.splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    )
    hay = "\n".join(prod_files) + "\n" + added
    hits = [name for name, rx in BOUNDARIES.items() if rx.search(hay)]
    e = len(hits)
    if INVARIANT.search(diff):
        e += 2
        hits.append("INVARIANT pinned in the diff (+2)")
    if len(CONCURRENCY.findall(diff)) >= 5:
        e += 1
        hits.append("async/concurrency surface (+1)")
    if ROUTE.search(diff):
        e += 1
        hits.append("new/changed route (+1)")
    return e, hits


def report(e: int, hits: list[str], commits: str) -> str:
    label, model, tests = classify(e)
    return "\n".join([
        "━━━ size estimate (advisory) ━━━",
        f"entanglement: {e} ({label})   signals: {', '.join(hits) or 'none'}",
        f"model:        {model}",
        f"tests:        {tests}",
        f"commits:      {commits}",
        "(commits decide phases S/M/L; entanglement decides proof — workflow.md)",
    ])


def from_plan(path: str, append: bool) -> str:
    text = open(path, encoding="utf-8").read()
    order = re.split(r"^##\s+Order\s*$", text, flags=re.M)
    steps = 0
    if len(order) > 1:
        tail = re.split(r"^##\s+", order[1], flags=re.M)[0]
        steps = len(re.findall(r"^\s*\d+\.\s+\S", tail, re.M))
    e, hits = score(re.findall(r"`?(src/[\w./-]+)`?", text), text)
    size = "L (branch from dev)" if steps >= 2 else "S or M (one commit, straight to dev)"
    out = report(e, hits, f"{steps or '?'} step(s) in `## Order` ⇒ {size}")
    if append:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n<!--\n" + out + "\n-->\n")
    return out


def main(argv: list[str]) -> int:
    if "--plan" in argv:
        i = argv.index("--plan")
        print(from_plan(argv[i + 1], "--append" in argv))
        return 0
    rev = next((a for a in argv[1:] if not a.startswith("-")), None)
    if rev:
        files = sh("git", "show", "--name-only", "--format=", rev).split()
        diff = sh("git", "show", rev)
    else:
        files = sh("git", "diff", "HEAD", "--name-only").split()
        diff = sh("git", "diff", "HEAD")
    if not files:
        print("size-estimate: empty diff.")
        return 0
    e, hits = score(files, diff)
    print(report(e, hits, "judge from the plan's `## Order`"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
