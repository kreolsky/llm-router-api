#!/usr/bin/env python3
"""INVARIANT-without-Why CI gate — zero-net-growth on Why-less INVARIANT markers.

Mirrors `debt-gate.py` (baseline-on-absolute-count: deterministic, no PR-data campaign).
Counts `INVARIANT:` markers (incl. tagged `INVARIANT(<tag>):`) over `src/` that have no `Why:` on the same line or within the next 2 lines
(shared logic: `marker_checks.py`). Fails CI when the count exceeds the committed
baseline (`.claude/baselines/invariant-why.json`). Existing Why-less markers are
grandfathered; new/touched code must include the Why. Escape hatch: intentionally
bump the baseline in the same PR with justification (`--update`).

Usage:
  invariant-why-gate.py            # compare to baseline, exit 1 on growth
  invariant-why-gate.py --update   # rewrite the baseline with the current count
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from marker_checks import invariants_missing_why, iter_files  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
CODE_DIRS = ("src",)
BASELINE = ROOT / ".claude" / "baselines" / "invariant-why.json"
INCLUDE_SUFFIXES = (".py",)


def count_missing() -> dict[str, int]:
    """Why-less INVARIANT count per file (deterministic)."""
    counts: dict[str, int] = {}
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for path in iter_files(base, INCLUDE_SUFFIXES):
            # Generated artifacts (openapi-typescript → api-types.gen.ts) mirror backend
            # docstrings verbatim, including INVARIANT prose — not hand-authored, so the
            # Why-adjacency rule does not apply.
            if ".gen." in path.name:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            n = len(invariants_missing_why(lines))
            if n:
                counts[str(path.relative_to(ROOT))] = n
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true", help="rewrite the baseline with the current count")
    args = ap.parse_args()

    counts = count_missing()
    total = sum(counts.values())

    if args.update:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({"total": total, "per_file": counts}, indent=2, sort_keys=True) + "\n")
        print(f"invariant-why-gate: baseline updated → total={total}")
        return 0

    if not BASELINE.exists():
        print(f"invariant-why-gate: baseline missing ({BASELINE.relative_to(ROOT)}); run `--update` first.")
        return 1

    baseline = json.loads(BASELINE.read_text())
    base_total = baseline.get("total", 0)
    diff = total - base_total

    print("━━━ invariant-why-gate — INVARIANT: without adjacent Why: ━━━")
    print(f"baseline total: {base_total}")
    print(f"current total:  {total}  ({'+' if diff >= 0 else ''}{diff})")
    if diff > 0:
        base_files = baseline.get("per_file", {})
        grew = {k: v for k, v in counts.items() if v > base_files.get(k, 0)}
        if grew:
            print("Files with new Why-less INVARIANTs:")
            for k, v in sorted(grew.items()):
                print(f"  {k}: {v} (baseline {base_files.get(k, 0)})")
        print(
            "\nWhy-less INVARIANT count GREW above baseline. Add a `Why:` within 2 lines\n"
            "of each new marker (documentation.md), or intentionally bump the baseline\n"
            "in the same PR with justification:\n"
            f"  python3 {Path(__file__).resolve().relative_to(ROOT)} --update"
        )
        return 1
    print("OK — no growth in Why-less INVARIANTs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
