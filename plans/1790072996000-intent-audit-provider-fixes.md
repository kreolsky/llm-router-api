# Fix plan: intent-audit `provider` — 3 marker fixes

Source: intent-audit 2026-09-22, system `provider` (src/providers/). Findings approved for fix.

Hard constraints:
- Comment/docstring text ONLY. Zero executable-code changes.
- Do not reflow, rewrap, or touch neighboring markers.
- No commit unless explicitly asked.
- CLAUDE.md wording is out of scope (/reality-audit territory, not intent-audit).

## Fix 1 — identity is opt-in (2 edits)

The marker reads as unconditional forwarding; `identity` unset disables it
(`base.py:79` accepts None → `services/base.py:117-118` returns None → plain
gateway headers). State both branches.

### 1a. `src/providers/base.py` (marker at ~L74)

Replace byte-verbatim:

```python
        # ARCH: single identity mode. `passthrough` forwards every client
        # header upstream verbatim minus the denylist
        # (core/header_policy.py); the headers are assembled by the service
        # layer per request and arrive via extra_headers.
```

with:

```python
        # ARCH: identity is opt-in. `passthrough`: every client header goes
        # upstream verbatim minus the denylist (core/header_policy.py),
        # assembled per request by the service layer via extra_headers.
        # Unset: no forwarding — plain gateway headers only.
```

### 1b. `src/services/base.py` (docstring at ~L114, `_build_identity_headers`)

Replace byte-verbatim:

```python
        passthrough: forward the client's headers verbatim minus the denylist.
        Returns None when the provider has no profile (behavior unchanged).
```

with:

```python
        passthrough: forward the client's headers verbatim minus the denylist.
        Unset identity: returns None — no client headers go upstream.
```

Kills the transition narration "(behavior unchanged)" (Q2 tell).

## Fix 2 — semaphore vs reuse-check (1 edit)

`src/providers/pool.py` (marker at ~L39). The current text says a changed
`max_concurrent` takes effect "after a config reload rebuilds the cache" —
since instance reuse landed, the real guarantee is the reuse equality check
(`providers/__init__.py:113` compares `live.provider_config != provider_config`;
a changed entry always fails it → rebuild → new semaphore).

Replace byte-verbatim:

```python
        # ARCH: per-instance concurrency gate (asyncio.Semaphore). Only created when
        # `max_concurrent` is a positive int; otherwise None (no limiting). The semaphore
        # is owned per-instance, so a config reload that changes max_concurrent only takes
        # effect after a config reload rebuilds the cache (semaphore is per-instance).
```

with:

```python
        # ARCH: per-instance concurrency gate (asyncio.Semaphore), only when
        # `max_concurrent` is a positive int; else None (no limiting). A changed
        # max_concurrent always rebuilds: the changed entry fails the reuse
        # equality check (providers/__init__.py), so the new gate applies.
```

## Fix 3 — noqa count (1 edit)

`src/providers/base.py` (comment at ~L250). Three defs carry the noqa
(`_make_request` ~L260, `_make_request_inner` ~L287, `_make_request_attempt`
~L329); the comment says "both" and lives only on the first.

On the single line, replace:

```python
    # WHY noqa ASYNC109 (both _make_request defs): `timeout` is the provider
```

with:

```python
    # WHY noqa ASYNC109 (all _make_request* defs): `timeout` is the provider
```

## Verify

1. `ruff check src/ tests/` — must stay clean (repo gate).
2. `grep -rn "behavior unchanged" src/` — empty.
3. `grep -n "both _make_request" src/providers/base.py` — empty.
4. `.venv/bin/python -m pytest tests/unit/test_provider_pool.py -q` — passes
   (sanity; comments only, nothing should change). Use the repo `.venv`
   (Python 3.12): bare `python3` may be 3.10, where `asyncio.TimeoutError`
   is not `TimeoutError` and 3 tests fail for unrelated reasons.

Report: files touched + verify output. Stop. No commit.
