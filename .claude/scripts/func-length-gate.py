#!/usr/bin/env python3
"""Function-length CI gate — zero-net-growth on functions longer than the limit.

Enforces the hard rule at `.claude/rules/workflow.md` ("Function > 50 lines → split").
The rule was a false signal (144 violations, never enforced); this gate turns it into
a real fence: existing violations are grandfathered into the baseline, and any NEW
long function fails CI. Splitting a long function shrinks the set (progress visible);
adding one requires bumping the baseline in the same PR (reviewable, no allowlist noise).

Set-based, not count-based (mirrors `debt-gate.py`'s escape-hatch CLI but keys by
function identity): a brand-new long function fails even if you paid down another in
the same file — displacement cannot hide growth. A key disappears only on rename/split/
deletion; a rename re-surfaces as "new" and needs a conscious baseline bump.

Scope: Python (`src/`), measured with the stdlib `ast` module — span =
`end_lineno - lineno + 1` (the `def` line to the last line; decorators excluded). TS/TSX
has no stdlib parser, so the rule stays advisory there until a TS measurement is added;
the four named worst offenders (audit 2026-07-28) are all backend Python.

Usage:
  func-length-gate.py            # compare to baseline, exit 1 on any NEW long function
  func-length-gate.py --update   # rewrite the baseline with the current violation set
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from marker_checks import iter_files  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
SCAN_DIR = ROOT / "src"
BASELINE = ROOT / ".claude" / "baselines" / "func-length.json"
LIMIT = 50  # rule: "> 50 lines"; violation when span > LIMIT
FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _functions(tree: ast.Module):
    """Yield (qualname, lineno, end_lineno) for every nested function/method.

    qualname chains enclosing class + function names so methods are `Class.method`
    and nested defs are `outer.inner` — stable across line shifts and reformatting,
    sensitive only to renames/relocations (which legitimately re-surface as "new").
    """
    def walk(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from walk(child, stack + [child.name])
            elif isinstance(child, FUNC_TYPES):
                yield (".".join(stack + [child.name]), child.lineno, child.end_lineno)
                yield from walk(child, stack + [child.name])
            else:
                yield from walk(child, stack)
    yield from walk(tree, [])


def measure() -> dict[str, dict]:
    """Return {key: {"span", "label", "line"}} for every function over the limit.

    key = "relpath::qualname"; a within-file qualname collision (two defs with the
    same dotted name, e.g. across conditional branches) is disambiguated by line.
    """
    violations: dict[str, dict] = {}
    if not SCAN_DIR.exists():
        return violations
    for path in iter_files(SCAN_DIR, (".py",)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except SyntaxError:
            continue  # unparseable file — don't crash the gate over one bad file
        rel = str(path.relative_to(ROOT))
        for qualname, lineno, end_lineno in _functions(tree):
            if end_lineno is None:
                continue
            span = end_lineno - lineno + 1
            if span <= LIMIT:
                continue
            key = f"{rel}::{qualname}"
            if key in violations:  # rare same-name collision — pin by line
                key = f"{rel}::{qualname}@{lineno}"
            violations[key] = {"span": span, "label": f"{rel}::{qualname}", "line": lineno}
    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true", help="rewrite the baseline with the current violation set")
    args = ap.parse_args()

    current = measure()

    if args.update:
        payload = {
            "limit": LIMIT,
            "scan_dir": str(SCAN_DIR.relative_to(ROOT)),
            "total": len(current),
            "violations": {k: {"span": v["span"], "label": v["label"]} for k, v in current.items()},
        }
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"func-length-gate: baseline updated → total={len(current)} (limit={LIMIT} lines)")
        return 0

    if not BASELINE.exists():
        print(f"func-length-gate: baseline missing ({BASELINE.relative_to(ROOT)}); run `--update` first.")
        return 1

    baseline = json.loads(BASELINE.read_text())
    base_v = baseline.get("violations", {})
    new_keys = [k for k in current if k not in base_v]
    paid_down = [k for k in base_v if k not in current]

    print(f"━━━ func-length-gate — functions > {LIMIT} lines (src, Python) ━━━")
    print(f"baseline violations: {len(base_v)}")
    print(f"current violations:  {len(current)}  (paid down: {len(paid_down)})")
    worst = sorted(current.values(), key=lambda v: v["span"], reverse=True)[:5]
    if worst:
        print("worst current (paydown targets):")
        for v in worst:
            print(f"  {v['span']:>4}  {v['label']}")

    if new_keys:
        print("\nNEW long functions not in baseline (zero-net-growth forbids this):")
        for k in sorted(new_keys, key=lambda k: current[k]["span"], reverse=True):
            v = current[k]
            print(f"  +{v['span']:>4}  {v['label']}")
        print(
            "\nSplit the function (workflow.md hard rule: Function > 50 lines → split), or\n"
            "intentionally grandfather it by bumping the baseline in the same PR with\n"
            "justification:\n"
            f"  python3 {Path(__file__).resolve().relative_to(ROOT)} --update"
        )
        return 1
    print("OK — no new long functions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
