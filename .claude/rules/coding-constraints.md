---
alwaysApply: true
---

# Coding Constraints

* Use the standard library and framework built-ins. No custom algorithms when a one-liner exists.
* No over-engineering, no redundant abstractions. Simplest tool for the job.
* No classes unless required for state management — providers are the standing exception:
  they carry an `httpx.AsyncClient` and their config.
* No nested conditional chains. Lookup dicts and early returns.
* Crash on missing configs/dependencies. No default values for critical data.
* Semantic naming and strict type hints mandatory. All code, comments and docstrings in English.
* Extract shared utilities only for genuinely reusable operations.
* **Deletion test** — before keeping an abstraction, imagine deleting it. Complexity
  vanishes ⇒ it was a pass-through, inline it. Complexity reappears spread across N callers
  ⇒ it earns its keep. **The unit under test is the whole module or table that owns the
  dispatch, not the arm you happen to be editing** — run it on the smaller unit and the
  answer is always "inline it into the parent", so the parent survives by construction.
  Editing one arm of a table keyed by a name the layer below already carries ⇒ the table is
  what you are testing.
* **A layer between this router and an external surface is kept by naming its consumer.**
  Surfaces: the upstream provider API, the client harness, the SQLite usage file, the YAML
  config. Name a `file:line` where something downstream gets from the layer what the surface
  below does not supply — a projection, a guard, a shape the consumer cannot read otherwise.
  Named ⇒ it stays, and the citation goes in the plan's `## Decisions` so the next session
  inherits the answer instead of re-deriving it. Not named ⇒ it goes, and its residual
  references go with it. This is the mirror of `workflow.md`'s discovery gate: that one
  prices a NEW subsystem, this one prices an existing one kept.
* **A named consumer counts only if it is itself REACHABLE FROM A ROOT.** Naming a reader is
  the half of the test that passes for dead code, so the walk goes UP from the named consumer
  to its own consumer, and terminates at a root or at nothing. A root is alive without a
  citation, and the list is short and closed: a request a client can actually make; a gate
  that BLOCKS (advisory output is not a root); a background task that actually runs; an
  operator ruling that the data is kept. Two greps end most walks early — *who WRITES the
  field that consumer reads* (no writer ⇒ dead however many readers), and *is that case
  already reported as an error* (a path that raises IS the contract; a silent fallback beside
  it is a contradiction, not a consumer).
  **An unreachable chain terminates in a QUESTION to the operator, never in an agent's
  deletion** — name the root it hangs on and what falls behind it; an unwanted root is a
  product decision and it is theirs. "The walk found no root" is never a reason to keep the
  layer quietly. Auditing a whole boundary — ranking roots by the subtree behind them, the
  question round, demolition order — is `/liveness-audit`.
* **A dead layer is not adjacent code — it goes in the session that FOUND it.** When a
  change, a review or a sweep walks past a layer and the walk above finds no root, the
  removal is not deferred to "its own task later": deferring is precisely what preserves it.
  The surgical-change rule below does not shield it — that rule governs code ADJACENT to
  your change, and a layer your change just proved dead is the task, not its neighbour. It
  rides in the same commit as the change that found it, split out only when the deletion
  tail is large enough that mixing makes either diff unreadable — a reviewability call,
  never a reason to postpone. Why: in the sibling project a dead render path survived ~300
  commits, correctly deferred as out-of-scope by every session that noticed it, and went in
  one sitting the moment its removal WAS the request.
* **One adapter is a hypothetical seam; two are a real one.** Don't introduce a
  port/protocol/injection point until something actually varies across it (prod + test
  counts as two). A single-adapter seam is indirection, not a seam.
* **Consolidating duplicate code into a shared helper**: if the two sites diverge in
  behaviour (different constants, timeouts, headers), STOP and ask which behaviour to keep.
  Never assume the divergence is accidental.
* **Surgical changes only**: don't "improve" adjacent code, comments or formatting. Match
  existing style. Remove imports/variables/functions that YOUR change made unused — don't
  touch pre-existing dead code unless asked. This governs code ADJACENT to your change; a
  layer the task is ABOUT is the task, and the consumer/root rules above decide it.
* **Cut only against the tree**: existing code goes in favour of a mechanism citable inside
  this repo, never in favour of a promise — a cut made on trust gets re-guarded later.
* **Size limits**: file > 500 lines → propose a split (soft). Function > 50 lines → split
  (hard) — gated by `func-length-gate.py` with zero-net-growth: existing violations are
  grandfathered in `.claude/baselines/func-length.json`; a NEW long function fails the gate.
  Split it, or bump the baseline in the same commit with justification.

## Removing or moving an existing symbol

* **Dependency removal audit**: `grep -rn 'import.*<package>' src tests` over all consumers;
  verify the replacement covers every use case before removing.
* **Internal-symbol refactor scan** (rename/move/remove a function/constant/private, or
  change *when* a value is resolved): grep the bare symbol name across `src/` AND `tests/`
  for the seams a module-import grep misses — deferred imports, `monkeypatch.setattr`
  string targets, `patch("mod.symbol")`, white-box private access (`obj._x`). Changing a
  value's *resolution timing* silently no-ops any monkeypatch of it. A bare-name grep is NOT
  enough once the symbol MOVED and the old module still re-exports it: the patch then
  succeeds and is wholly inert. Check not "where the name appears" but **which namespace the
  CALLER resolves it from** — the test's patch target must be that one.

## Read the entry file — don't infer a contract from one symbol

Before building ON or NEXT TO an existing mechanism (a provider capability, the stream
processor, the capabilities cache, the usage writer), READ its `SYSTEM:` entry file —
docstring plus `ARCH:`/`INVARIANT:`. Do NOT reconstruct its contract from a single signal
(one signature, one regex, one config key): a particular signal describes an edge case or a
legacy tolerance, not the canon. This is the design analog of "observe before patch": there,
reproduce before patching; here, read the entry file before designing on top of it. The
trigger is the moment you are about to write "new format / new key / new target" over
something existing.

Reading the entry file tells you what the mechanism DOES; whether it should EXIST is the
consumer/root rules above. A docstring, an `ARCH:` and a full test suite are what a
pass-through looks like from the inside too.

**Adding a case for a NAME to a dispatch site obliges a repo-wide grep of that name first**
— a `reasoning_dialect`, a provider type, an upstream response shape, an error code, a
forwarded header, anything dispatched on. An existing arm for the same name means the case
is ALREADY OWNED: feed that arm its inputs instead of shipping a worse duplicate of a
handler that was already better. Cite the FUNCTION that owns the case, never the line that
merely explains the symptom — stopping at "this is the line that renders the field" is what
hides the existing arm forty lines below.

## Anti-mirage validation

After generating or modifying >20 lines, verify: every `import` references a real module;
every call matches a real signature; every type exists; new env vars are in
`ConfigManager._ENV_SETTINGS` **and** documented in `CLAUDE.md`; new packages are in
`requirements.txt` (runtime) or `requirements-dev.txt` (tests only); every config key the
code reads exists in the YAML schema. If unsure whether an API exists, grep before using it.
