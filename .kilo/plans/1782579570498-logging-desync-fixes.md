# Logging-Desync Fixes (Audit Remediation)

Minimal-risk patch addressing three audit findings on top of the completed
`arch-audit-remediation` work: the `RULES.md` vs `ChatService` logging
contradiction (E2), a stale docstring in `auth.py`, and a noisy test class.

Scope: 3 source/test files. No functional behavior change. Unit suite stays
green.

## Context (verified in code)

- `logger.request_context(...)` in `src/services/chat_service/chat_service.py`
  (lines 56–110) emits **two** service-level INFO lines per request
  (`Started: Chat Completion` + `Completed: Chat Completion | duration=…`).
  Combined with middleware Incoming/Outgoing that is **4 INFO per chat request**,
  contradicting `RULES.md:85` (“One service-level INFO entry per request”).
- Removing it is safe for error visibility: `create_error()` already logs at
  error level (`src/core/error_handling/error_handler.py:36,38`), so the only
  thing lost is the redundant “Chat Completion failed” string.
- For streaming, the `Completed` line is semantically wrong anyway: the handler
  returns an async generator before the stream finishes, so it logs “completed”
  prematurely.
- `TestProvider` in `tests/unit/test_base_provider.py` has an `__init__` and is
  named with a `Test` prefix → pytest emits
  `PytestCollectionWarning: cannot collect test class 'TestProvider'` on every
  run. All 6 references are local to that one file.
- Docstring of `get_api_key` (`src/core/auth.py:20`) still claims it
  “Sets request.state.project_name”, which no longer exists after the
  `RequestContext` refactor.

## Decisions (locked)

1. **E2 — drop the `logger.request_context(...)` wrapper** from
   `ChatService.chat_completions()`. Keep the surrounding `try/except`
   (→ `create_error`). Do **not** add a new service INFO: middleware
   Incoming/Outgoing remains the canonical request bookend, and
   `embedding_service` already sets the “one optional success-INFO” pattern.
2. **Tighten `RULES.md §Logging`** so doc and code agree: Incoming/Outgoing are
   canonical; services emit at most one optional success-INFO; chat emits none
   (streaming completes after handler return); errors are logged via
   `create_error`.
3. **Rewrite the stale docstring** in `auth.py`.
4. **Rename `TestProvider` → `ProviderStub`** (idiomatic; preferred over
   `__test__ = False`).

## Ordered task list

- **T1.** `src/services/chat_service/chat_service.py`: remove the
  `with logger.request_context(operation="Chat Completion", ...)` block
  (lines 56–62) and dedent its body (lines 63–110), keeping the outer `try:`
  above it and both `except` clauses. `import inspect` stays
  (`inspect.isasyncgen` is still used).
- **T2.** `RULES.md` §Logging (lines 82–85): rewrite the convention so it no
  longer contradicts the code — middleware Incoming/Outgoing is the canonical
  request bookend; a service MAY emit at most one optional success-INFO
  (see `embedding_service`); `chat_service` relies solely on the middleware
  bookends because streaming completes after the handler returns; request
  errors are surfaced via `create_error`.
- **T3.** `src/core/auth.py:20`: replace the “Sets request.state.project_name”
  sentence with an accurate description — the dependency rebuilds the typed
  `RequestContext` on `request.state.request_context` with `project_name`
  attached (via `ctx.with_project_name(...)`).
- **T4.** `tests/unit/test_base_provider.py`: rename class `TestProvider` →
  `ProviderStub` and update all 6 references (lines 20, 44 docstring, 59, 200,
  208, 214).
- **T5.** Validate: run `python -m pytest tests/unit/ -q` — expect
  `200 passed` with **no** `PytestCollectionWarning`. Manually confirm that a
  chat request now logs exactly Incoming + Outgoing (plus DEBUG lines only when
  DEBUG is on).

## Risks & mitigations

- **Loss of the “Completed” duration line.** Mitigation: the middleware Outgoing
  line already carries `time={…}ms` (`src/api/middleware.py:103`), so request
  timing remains visible.
- **External consumers alerting on the literal `Completed: Chat Completion`
  string.** Mitigation: T2 documents the new convention; alert owners must be
  notified out-of-band. Considered out of scope for this patch.
- **Missing a `TestProvider` reference during rename.** Mitigation: grep
  confirmed all 6 references are inside `test_base_provider.py` only.

## Out of scope

- E1 (bulk conversion of `extra={...}` → kwargs logging) — intentional de-scope.
- Adding the two missing insurance tests (typed context in middleware,
  reload-callback → `aclose`).
- The fire-and-forget task pattern in `clear_provider_cache`.

## Validation

- `python -m pytest tests/unit/ -q` → `200 passed`, no
  `PytestCollectionWarning`.
- Manual: chat request logs exactly Incoming + Outgoing INFO lines (no
  `Started`/`Completed`); error path still logged via `create_error`.
