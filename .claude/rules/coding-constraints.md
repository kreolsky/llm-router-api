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
  ⇒ it earns its keep.
* **One adapter is a hypothetical seam; two are a real one.** Don't introduce a
  port/protocol/injection point until something actually varies across it (prod + test
  counts as two). A single-adapter seam is indirection, not a seam.
* **Consolidating duplicate code into a shared helper**: if the two sites diverge in
  behaviour (different constants, timeouts, headers), STOP and ask which behaviour to keep.
  Never assume the divergence is accidental.
* **Surgical changes only**: don't "improve" adjacent code, comments or formatting. Match
  existing style. Remove imports/variables/functions that YOUR change made unused — don't
  touch pre-existing dead code unless asked.
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

## Anti-mirage validation

After generating or modifying >20 lines, verify: every `import` references a real module;
every call matches a real signature; every type exists; new env vars are in
`ConfigManager._ENV_SETTINGS` **and** documented in `CLAUDE.md`; new packages are in
`requirements.txt` (runtime) or `requirements-dev.txt` (tests only); every config key the
code reads exists in the YAML schema. If unsure whether an API exists, grep before using it.
