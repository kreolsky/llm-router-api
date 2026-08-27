---
name: implement
description: "Orchestrate workflow phases. Выполни план, приступай к работе, приступай к реализации, реализуй, начинай, делай, работай, execute plan, start working, begin implementation."
---

# Workflow Orchestrator

Execute the `.claude/rules/workflow.md` phases in order. Phase definitions, the sizing table
and the skip rules live there — do not duplicate them, refer to them.

## 1. Locate the plan

- The plan is the one the user named. Approved plans live in `plans/`; a `## Progress`
  section, if present, is the resume point.
- No plan named → fall back to the newest (`ls -t plans/*.md | head -1`) and **say which one
  you picked and that none was named** — a guessed plan is not an approved one.
- Display: `━━━ PLAN LOADED ━━━` + filename + first heading.
- If no plan exists, ask the user to describe the task or enter plan mode first. **HALT.**
- **Shape check — run it, do not eyeball it:**
  `python3 .claude/scripts/plan-shape-gate.py <plan path>`. Non-zero ⇒ print the output and
  **HALT**: offer to rewrite the plan to shape (rewrite, never append), or to proceed once
  the user says so. This is the gate's hard point — a plan is usually still uncommitted when
  its implementation commits, so execution is the last moment where reshaping is free.

## 2. Phase 0 — Scope

Determine S/M/L per the sizing table (commits × entanglement — never file count). Run the
discovery gate: `SYSTEMS.md` → `grep -rn "SYSTEM:" src/` → read the entry files. Output the
`━━━ SCOPE ━━━` block. **HALT** for confirmation.

## 3. Phases 1–2 (L only)

- **Phase 1**: output the filled checklist from `.claude/rules-scoped/integration.md`.
- **Phase 2**: failing tests before implementation, per the TDD cycle (`/tdd`).

For S and M output "Phases 1–2: skipped — <S|M>, single commit" and proceed. S and M still
write tests in Phase 3; what L adds is the red run as a gate.

## 4. Phase 3 — Implementation

Output `━━━ PHASE 3: IMPLEMENTATION ━━━`. Work the plan step by step:

- Tests after each step; breadth from the entanglement table, commands in
  `.claude/rules-scoped/testing-ops.md`. Rebuild the container — the image copies source.
- Add `ARCH:` / `INVARIANT:` / `WHY:` markers per `documentation.md`; regenerate `SYSTEMS.md`
  if a `SYSTEM:` marker changed.
- Ambiguous step → halt and ask.
- After the final step: **drive the affected flow live** against `:8777` (streaming and
  non-streaming as applicable, plus the refused principal for any access change) and record
  the output verbatim — reality-facing acceptance per `workflow.md` Phase 4. A
  tests/docs/config-only diff states the exemption instead.

## 5. Phase 4 — Review

M or L, or any review-gate trigger (hot path, new module, user said "done"/"push") → invoke
`/review` (mandatory, do not ask). An S with no trigger → output the skip reason. **HALT**
for approval. Do NOT gate on file count.

## 6. Phase 5 — Commit & Retro

Run `.claude/scripts/pre-commit-gates.sh` **unpiped**. Output `━━━ PHASE 5: COMPLETE ━━━`.
**HALT** — wait for an explicit commit request. If steps remain, update the plan's
`## Progress` so the next session can resume from it.
