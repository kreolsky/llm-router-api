---
alwaysApply: true
---

# Documentation as Architecture

Code is the single source of truth. Document only what is **not inferable from the code**:
traps, not operations.

## Markers (grep-able)

* `ARCH:` — an architectural decision, ONLY when cross-cutting or on a system boundary
  (provider abstraction, request path, reload semantics), and in the entry file (first 10
  lines) of any new package under `src/`. A LOCAL non-obvious choice is `WHY:`, not `ARCH:` —
  threshold: would another subsystem's author need to know this?
* `INVARIANT:` — a constraint that must hold (access checks, one-INSERT-per-request, pool
  drain order, SSE frame boundaries). Always followed by a `Why:` on the same line or within
  the next 2 lines — gated by `invariant-why-gate.py` (existing Why-less markers are
  grandfathered; intentional growth = `--update` the baseline in the same commit with
  justification). Optional severity tag for the critical class:
  `INVARIANT(data-loss|corruption|security|persisted):` — tag ONLY where violating the rule
  loses or corrupts data, breaks access control, or fixes the shape of already-stored data.
* `WHY:` — a non-obvious implementation choice (an SDK workaround, a lazy import, a format
  conversion, an upstream quirk).
* `DEBT: <what> — Why deferred: <reason>` — a CONSCIOUSLY deferred refactor or known
  shortcut left in place on purpose (not a bug, not a TODO for a missing feature). Goes ON
  the load-bearing line, so `grep -rn "DEBT:" src/` is a live ledger; `debt-gate.py` holds it
  at zero net growth. `Why deferred:` is mandatory. NOT for routine "could be nicer" nits,
  and NOT a substitute for `INVARIANT:`. A `DEBT:` resolved by a refactor is DELETED with it.
* `SYSTEM: <name> — <desc>` — the ENTRY POINT of a named subsystem, so
  `grep -rn "SYSTEM:" src/` is a clean index. ONLY on the entry file, at most one per
  subsystem. NEVER on an incidental line or as a cross-reference from a non-entry file — that
  dilutes the index; cross-references use prose: `see SYSTEM: <name>`. Adding, renaming,
  removing or moving one ⇒ regenerate `SYSTEMS.md`
  (`python3 .claude/scripts/systems-index.py --write`) and commit it; `pre-commit-gates.sh`
  blocks on drift. Aliases (including Russian task nouns) are hand-maintained in
  `.claude/systems-aliases.json`.

## No process provenance in comments

A comment states the CONTRACT, never the process that produced it. Plan slugs and paths,
`Stage N` / `Phase N`, `audit fix #N`, `review F3`, bare dates and `plans/…` references are
all one genre — they rot. Delete the attribution; the rule text it annotated stays VERBATIM.
Deleted provenance is not lost — git history is the archive.

Historical narrative ("before / used to / was removed when Ollama went away") describes a
transition, not the current contract: delete it rather than rewrite it into present tense.

**Touching a file means cleaning its header to that shape** — the whole header, not only the
lines your change touched. This is the one place the surgical-change rule does not apply, and
it is deliberate: nobody is going to sweep the tail, so opportunistic cleanup on the files
people actually open is what shrinks it. Scope stays comments-only (no logic, imports or
formatting), so the diff is still reviewable. Two things this does NOT license: rewriting
`INVARIANT:` text (strip its attribution, never its rule), and promoting a marker between
classes — only the local-`ARCH:` → `WHY:` demotion is in scope.

## Single home for contracts

A contract lives in ONE place — the in-code marker on the load-bearing line. `CLAUDE.md`,
rules files and lessons REFERENCE it (`see INVARIANT in src/core/usage_db/writer.py`),
never restate it: a copied contract drifts from the code silently.

## Docstrings

* Every module: a one-line module docstring. **Tier 1** (non-obvious behaviour, side
  effects, error conditions): a full docstring. **Tier 2** (name + types tell the story): one
  line. **Tier 3** (trivial helpers, Pydantic models): none.
* Never document what the type hints already say, or what stdlib does.

## Decision pinning

User-stated business logic (access order, what is logged, what is billed, reload semantics,
retry policy, what the dashboard shows) MUST be captured in the code that enforces it — a
contract living only in chat is a future regression. On the **load-bearing line** (the
branch, early return or gate):

```python
# INVARIANT: <rule in the user's plain words>.
# Why: <the reason they gave>.
```

The `Why:` is what survives refactors; without it the marker gets deleted. `ARCH:` for
structural, `WHY:` for one-off, `INVARIANT:` for behavioural. No asking, no batching, no
candidate list — an ask that costs a turn collapses to never.

* **A bugfix in a repeatedly-regressing area** → the fix MUST add or tighten an
  `INVARIANT:` + `Why:` on the broken line. `/review` warns if it is absent.
* **Don't** restate what the code says, add `SPEC: file §N` back-refs, or mark trivial code.
* **Maintenance**: markers move with their code. A marker contradicting behaviour → stop and
  ask which is wrong; never silently fix either side.
