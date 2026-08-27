---
name: review
description: Post-implementation self-review. Ревью кода, ревью изменений, code review, проверка, самопроверка после реализации.
---

# Post-Implementation Self-Review

Phase 4. The trigger list, the self-review checklist and the decision-pinning check live in
`.claude/rules/workflow.md` and `.claude/rules/documentation.md`. **Never auto-fix** —
present findings + a fix plan, wait for approval.

## 1. Workflow compliance

```
━━━ WORKFLOW COMPLIANCE ━━━
TDD:         [PASS / VIOLATION — tests after impl, or missing for new endpoints]
Checklist:   [PASS / SKIPPED — reason / N/A]   (.claude/rules-scoped/integration.md)
Doc markers: [PASS / MISSING — list]           (ARCH on boundaries, INVARIANT+Why, module docstrings)
Acceptance:  [PASS — live-drive evidence exists / VIOLATION — no live observation / EXEMPT — no runtime surface]
Gates:       [pre-commit-gates.sh output]
```

`Acceptance` per `workflow.md` Phase 4: a diff touching `src/` needs a live drive of the
affected flow — streaming diffs show the frames from `curl -N`, access diffs show BOTH the
allowed and the refused key, config diffs cross an actual hot reload — with the output
captured verbatim. tests/docs/config-only diffs are EXEMPT and say so.

## 2. Diff review

`git diff --stat` (only the intended files) → read the full diff for incomplete access
guards, duplicated literals, formatting, config-schema drift → grep old identifiers after
any rename, including `monkeypatch`/`patch(...)` string targets in `tests/`.

## 3. Architecture conformance

Align with `CLAUDE.md`: thin gateway (no business logic beyond routing), provider isolation,
config-driven, fail fast. Access check before existence check. Errors through
`create_error(ErrorType, …)`. Request context via `core.context.request_context`. No direct
`os.getenv` in providers/services.

## 4. Decision-pinning check

Per `documentation.md`: a bugfix in a repeatedly-regressing area must add or tighten an
`INVARIANT:` / `ARCH:` / `WHY:` with a `Why:`. Flag any new `INVARIANT:` lacking a `Why:`,
and any marker contradicting the user's latest stated rule. A new marker that met no pin
trigger is flagged as noise to drop, not kept as harmless.

## 5. Tests & gates

New or changed logic has tests in `tests/`. Run the breadth the entanglement table demands,
then `.claude/scripts/pre-commit-gates.sh` **unpiped**.

## 6. Summary — card form (`subagent-contract.md`)

**What moved** · **Evidence** (checks actually run, output verbatim) · **Residual**
(findings + fix plan, awaiting approval) · **Outside scope**. Wait for approval.
