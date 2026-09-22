---
name: intent-audit
description: Audit one mechanic's in-code intent markers against the code and against today's product decisions. Аудит намерений, сверь комментарии с кодом, устарели ли инварианты, не лишний ли слой, проверь ARCH и INVARIANT, intent drift, stale markers.
---

# Intent Audit

Reviews the **intent layer** of ONE named mechanic: its `ARCH:` / `INVARIANT:` / `WHY:` /
`SYSTEM:` / `DEBT:` markers and module docstrings. `/review` judges a diff and
`/reality-audit` judges the prose in `CLAUDE.md`/`RULES.md`/`lessons`; neither reads these.

Run it on a mechanic that has been reworked, that keeps regressing, or that sits on an
external surface (an upstream provider API, a client harness, the usage DB). Cadence is
yours — there is no gate, because
every finding here is a judgement call.

**Scope is one mechanic, never the repo.** Ask which one if the request does not name it.

## 1. Narrow the reading list

    python3 .claude/scripts/marker-drift.py --system <name>     # or --path <dir>

Ranks markers whose guarded code was changed by commits NEWER than the marker line. It is
a reading list, not a verdict — and it is blind to a marker that is wrong from birth, so
also read the entry file's header in full. Ignore a file that was reformatted wholesale
(blame resets every line and floods the ranking).

## 2. Three questions per marker, in order

A marker failing Q2 or Q3 is NOT fixed by re-stating it — answer Q1 last.

**Q1 — True?** Does the code under it still do what it says? Report `WAS (marker): … /
NOW (code): …` with the `file:line` of the code, not of the comment.

**Q2 — Current?** Does it state the product decision that holds TODAY? The tells: it is
named after a retired component, a deleted mode or an abandoned approach; it defines a
thing by contrast with something no longer in the tree; it carries `(plan <slug> step N)`
/ `Stage N` provenance, or narrates a transition ("no longer", "formerly", "used to").
This class is the expensive one: it does not read as stale, so the next session takes it
as the live contract and rebuilds what it describes.

**Q3 — Earned?** Is the layer it defends still ours? Apply `coding-constraints.md`'s
layer-consumer rule literally: name a consumer `file:line` AND the producer that writes
what the consumer reads. No producer ⇒ dead, however many readers. A case already
reported as a failure elsewhere is not a consumer. For an external surface the default is
USE, not BUILD — grep `vendor/dsh/packages/` before accepting that a layer is ours.

## 3. Report — then stop

Order findings by what is BIGGEST, largest candidate first with its line count, even when
it needs its own task (`coding-constraints.md`). A few dozen lines offered alone is not an
audit result. State what a reader would wrongly conclude from each stale marker — that
consequence is the finding; the line is supporting detail.

**Never auto-fix, never delete.** A marker contradicting code means one of the two is
wrong and the user decides which (`documentation.md`, Maintenance). A dead layer found
here becomes its own task with its own plan whose only deliverable is the absence — folding
the removal into whatever change found it is how it gets deferred forever.

Close with a fix ORDER, not a question: vocabulary first (one place, once), then the lines
that copy it. Wait for approval before editing anything.
