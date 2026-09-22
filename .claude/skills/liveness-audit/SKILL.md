---
name: liveness-audit
description: Walk a layer up to its root and report what falls if the root goes. Аудит достижимости, что можно удалить, мёртвый код, живой ли слой, поиск мёртвых деревьев, нужен ли этот слой, кто это вообще использует, dead tree audit, root reachability, what can we delete.
---

# Liveness Audit

Answers ONE question: **is this alive, and what falls with it?** Not "does something call
it" — that is reference counting, and reference counting keeps garbage. The whole test,
the closed root list and the two supporting greps are the layer-reachability rule in
`.claude/rules/coding-constraints.md`; read it, do not re-derive it.

Sibling audits, different questions: `/intent-audit` checks markers against code,
`/reality-audit` checks prose against code. Neither walks reachability.

## 0. Pick the surface, not a symptom

Start from a boundary or a register item — a directory, a subsystem in `SYSTEMS.md`, a
table, a `DEBT:` line from `grep -rn "DEBT:" src/`. "This
function looks unused" is the wrong altitude: the smallest safe deletion is always found
first bottom-up, and stopping there reads as an answer when it is not.

Ask which surface if the request does not name one.

## 1. Walk UP from each named consumer

For every layer under the surface: name a consumer `file:line`, then ask what keeps THAT
consumer alive, and repeat. Terminate at a root or at nothing — the root classes are the
short closed list in the rule.

Two greps end most walks early, and both are cheap:

- **Who WRITES the field the consumer reads?** No producer ⇒ dead, however many readers.
- **Is that case already reported as a failure elsewhere?** A path that raises or toasts IS
  the contract; a silent fallback beside it is a contradiction, not a consumer.

Read the entry file of every system on the walk (`.claude/rules/coding-constraints.md` →
read the entry file). A `SYSTEM:` docstring routinely names the root outright.

## 2. Report by descending size of WHAT FALLS IF THE ROOT GOES

Per root, count what becomes unreachable if it goes — `wc -l` over the files, plus the
schema columns, jobs, endpoints and locale keys behind it. That number is the ranking key,
and it is measured: a register whose sizes are guesses cannot be ordered.

Rank by the subtree behind each root, never by the candidate in front of you — otherwise a
300-line leaf outranks a one-line product decision worth 1052. Name the biggest candidate
with its line count even when it needs its own task, BEFORE any small one: a finding of a few
dozen lines, offered alone, is not an audit result.

`.claude/scripts/deletion-tail.py <name>` finds residual references so a later sweep lands
in one commit instead of three.

## 3. One numbered round of root questions — then stop

Deliver every question whose prerequisites are settled, in a single message, largest
subtree first. Each carries the answer the audit recommends and the weight behind it. A
question depending on another still open waits for the next round.

```
❓ **R1** — **<root>**: is this still wanted? <what it is, in product terms>
   Falls if cut: <N lines / files / columns>
➡️ <recommended answer + the premise it rests on>
```

A bare question with no recommendation is half a turn — the audit did the reading, so it
owes its own answer. State the premise: the operator often holds a fact that voids it.

## 4. Never delete here

The audit's deliverable is the ranked question round. A root ruled unwanted becomes its
own task whose only deliverable is the absence — folding removal into the audit that found
it is how it gets deferred forever.

**Demolition order once approved is intent → root → sweep, and only the middle step is
dangerous**: kill the intent (the product decision, the doc, the manifest) and the root stops
being a root; cut the root under a live drive; the subtree is then unreachable and its removal
proves nothing, so it is mechanical work a cheap model finishes. Leaf-first demolition in the
same window cost 33 `fix` commits in 11 days — see
`docs/pi-to-dsh-migration-postmortem.md` § "1 сентября".

"The walk found no root" is never a reason to keep a layer quietly. Say it, with the size.
