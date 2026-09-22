---
name: grill
description: Interrogate a plan, design or decision until nothing is silently assumed. Погоняй меня по плану, разбери решение, задай вопросы, что я упускаю, стресс-тест плана, прожарь, grill me, stress-test this design.
---

# Grill

Runs before or inside Phase 0–1 of `.claude/rules/workflow.md`, ahead of `ExitPlanMode`.
The output is a shared understanding, never code. The discovery gate still applies:
`SYSTEMS.md` lookup → `grep -rn "SYSTEM:" src/` → read the entry files BEFORE the first
round. **A question answerable by grep is not a question for the user.**

## The design tree

Every decision branches into the decisions hanging off it. The **frontier** is every
decision whose prerequisites are already settled — what can be asked *now* without guessing
at answers not yet heard.

Work in **rounds**. Ask the whole frontier in one message. A question whose answer depends
on another question open in this round belongs to a *later* round.

```
❓ **Q1** — **<title>**: <body; options if there are options>

➡️ <your recommended answer>
```

Every question carries a recommendation, and the premises under it are stated rather than
assumed — the user often holds one fact that voids the whole recommendation. Then **wait**.
Answers reshape the tree: settled decisions push the frontier outward. Recompute, ask the
next round.

## Facts are yours, decisions are theirs

A frontier question needing a fact from the environment (a file, the container, the usage
DB, an upstream response) is never asked — run the command or dispatch a subagent. Don't
block on it: a running lookup is an unsettled prerequisite, so only the questions downstream
of it wait, and the rest of the frontier is asked now. Subagent dispatches follow
`.claude/rules/subagent-contract.md`.

## Sharpen the language as you go

Three interrupts, fired the moment they apply — mid-sentence, never batched into a summary:

- **Fuzzy term → propose the canonical one**, and name what you are giving up. "You said
  «модель» — the `models.yaml` registry entry, the upstream model id, or the provider
  instance?" Then: `model entry` (not: model, alias).
- **Conflict with a term already pinned** — `CLAUDE.md`, a `SYSTEMS.md` alias, an
  `INVARIANT:` on the line — is called out immediately, never quietly translated.
- **Word disagrees with code → quote the code back.** "You said an unknown client header is
  dropped; `src/core/header_policy.py` is fail-open and forwards it — which is right?"

A resolved term that turns out to be load-bearing business logic is a decision-pinning
candidate (`documentation.md`) — it goes onto the line that enforces it, never into a
glossary file. Grilling does not ask about pinning: note the candidate and let the pin
triggers decide. A term settled here is the FIRST statement of a rule, which is exactly what
does not earn a pin yet.

## Done

The frontier is empty: every branch visited, nothing silently assumed. Then a short Russian
summary, and the user confirms before anything is built.
