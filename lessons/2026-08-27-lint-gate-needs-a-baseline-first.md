---
category: tooling-gap
systems: [api-app]
---

# Lint cannot become a gate before its backlog is a baseline

## What happened

While installing the local gate block, ruff was measured against the tree for the first time:

```
$ ruff check src tests
Found 526 errors.
[*] 388 fixable with the `--fix` option
```

There is no ruff config in the repo (no `pyproject.toml`, no `.ruff.toml`), so those 526 are
against ruff's defaults, and the project has no CI at all — nothing had ever run it.

## Root cause

A gate is only a fence if it can be green. Wiring ruff into `pre-commit-gates.sh` on day one
would have made every commit start red, and a gate that is always red is one people route
around — which then costs the gates that DO work their credibility.

## Actionable rule

A new check joins the blocking set only once it is green: either the backlog is cleaned, or
it is frozen into a committed baseline with zero-net-growth semantics (the shape
`invariant-why-gate.py`, `debt-gate.py` and `func-length-gate.py` already use — existing
violations grandfathered, a NEW one fails). Until then it prints an advisory count and does
not block.

```bash
# wrong — a gate nobody can clear
run_gate "ruff" ruff check src tests

# right — advisory until the backlog is a baseline
N=$(ruff check src tests | grep -cE '^(src|tests)/')
[ "$N" -gt 0 ] && printf '  note  ruff: %s finding(s) — advisory, not gated\n' "$N"
```

Owner: `.claude/scripts/pre-commit-gates.sh` (the advisory block and its comment).
