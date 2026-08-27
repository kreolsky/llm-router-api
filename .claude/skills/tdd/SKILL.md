---
name: tdd
description: TDD initialization. Write failing tests before implementation. Тесты, написать тесты.
---

# TDD Initialization

Drives Phase 2 of the workflow. Cycle and rules live in `.claude/rules/workflow.md`, test
commands in `.claude/rules-scoped/testing-ops.md` — follow them; don't restate.

## 1. Understand — **HALT for confirmation**
Restate the bug/feature concretely: current behavior, expected behavior, code paths involved.

## 2. Write failing tests
- pytest in `tests/unit/` for logic, `tests/api/` for anything a client observes over HTTP.
- Test the principal that must be REFUSED, not only the one that passes (`.claude/rules/testing.md`).
- Run them; all new tests must fail **for the right reasons** (verify the failure messages).
- Never modify existing tests to make failing code pass.

## 3. Plan from tests — **HALT for approval before any implementation**
Tests are the plan. The plan file has ONE shape — `## Decisions` · `## Risks` · `## Order` ·
`## Not doing` · `## Validation` — max 120 lines, English only, written to `plans/`
(`workflow.md` → Plans). Check it with `python3 .claude/scripts/plan-shape-gate.py <path>`.
