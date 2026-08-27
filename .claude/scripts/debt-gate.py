#!/usr/bin/env python3
"""Debt-ledger CI gate — zero-net-growth on the live `DEBT:` ledger.

Distinct from `regression-radar.py`, which is ADVISORY by design (workflow.md /
documentation.md) and must NEVER gate. This gate fails CI when the total `DEBT:`
marker count over `src/` exceeds the committed baseline
(`.claude/baselines/debt.json`). Intentional new debt = update the baseline in
the same PR (reviewable, no allowlist noise).

Stdlib-only (no grep dependency) so it runs identically on the CI host.

Usage:
  debt-gate.py            # recompute count, compare to baseline, exit 1 on growth
  debt-gate.py --update   # rewrite the baseline with the current count
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from marker_checks import iter_files  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
CODE_DIRS = ("src",)
BASELINE = ROOT / ".claude" / "baselines" / "debt.json"
INCLUDE_SUFFIXES = (".py",)
DEBT_RE = re.compile(r"\bDEBT:")


def count_debt() -> dict[str, int]:
    """Count `DEBT:` markers per top-level area (best-effort, deterministic)."""
    counts: dict[str, int] = {}
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for path in iter_files(base, INCLUDE_SUFFIXES):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            n = sum(1 for line in text.splitlines() if DEBT_RE.search(line))
            if n:
                counts[str(path.relative_to(ROOT))] = counts.get(str(path.relative_to(ROOT)), 0) + n
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true", help="rewrite the baseline with the current count")
    args = ap.parse_args()

    counts = count_debt()
    total = sum(counts.values())

    if args.update:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps({"total": total, "per_file": counts}, indent=2, sort_keys=True) + "\n")
        print(f"debt-gate: baseline updated → total={total}")
        return 0

    if not BASELINE.exists():
        print(f"debt-gate: baseline file missing ({BASELINE.relative_to(ROOT)}); run `debt-gate.py --update` first.")
        return 1

    baseline = json.loads(BASELINE.read_text())
    base_total = baseline.get("total", 0)
    diff = total - base_total

    print(f"━━━ debt-gate — DEBT: ledger ━━━")
    print(f"baseline total: {base_total}")
    print(f"current total:  {total}  ({'+' if diff >= 0 else ''}{diff})")
    if diff > 0:
        current_files = {k: v for k, v in counts.items()}
        base_files = baseline.get("per_file", {})
        new_files = {k: v for k, v in current_files.items() if k not in base_files}
        if new_files:
            print("New DEBT: markers (not in baseline):")
            for k, v in sorted(new_files.items()):
                print(f"  +{v}  {k}")
        print(
            "\nDEBT ledger GREW above baseline. Either pay down the new debt, or\n"
            "intentionally bump the baseline in the same PR:\n"
            f"  python3 {Path(__file__).resolve().relative_to(ROOT)} --update"
        )
        return 1
    print("OK — no net debt growth.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
