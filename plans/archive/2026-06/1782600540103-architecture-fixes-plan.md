# Architecture Fixes — nnp-ai-router

Plan to fix all findings from the architecture audit. Ordered by priority; each task
lists files touched, concrete change, and validation step.

## Context

Audit found: (1) a shared-state race in StreamProcessor, (2) a misnamed logger that
silently drops all error logs, (3) a creation race in the provider cache, (4)
fire-and-forget usage recording that loses tasks/errors, plus a set of cleanliness
issues. The gateway is a thin OpenAI-compatible router: `api → services → providers →
httpx`. All changes must preserve layering (services never do HTTP directly; providers
own httpx pools; config drives everything).

## Decisions (resolved with user)

- **Usage recording**: track tasks in a set + `add_done_callback` (WARNING on failure);
  `record_usage` logs instead of `except: pass`. Latency unaffected (still async).
- **Provider cache**: `asyncio.Lock` + new `rebuild_provider_cache(config, cm)` that
  builds a temp dict, atomically swaps the cache, and background-closes old pools. On
  validation failure the old cache is kept. Called at startup and as the reload callback.
- **Provider HTTP errors**: dedicated factory `create_provider_http_error(...)` (dynamic
  status code), same OpenRouter shape; `ErrorType` enum untouched.
- **StreamProcessor**: per-stream local state, live sanitization flag.
- **Provider API**: split `chat_completions` into `chat_completions` (dict) and
  `chat_completions_stream` (async generator); service dispatches on the `stream` flag.
- **Port**: no code change (8777 host / 8000 container is correct); `CLAUDE.md` note only.

### Out of scope (deferred tech debt)

- Module-level globals (`_provider_cache`, `usage_db._connection`, `_logger_instance`).
  Note in plan; no change.

### Known limitation

`reload_config` swaps `self.config` *before* invoking reload callbacks. If
`rebuild_provider_cache` fails, config is already new while the cache holds old
instances → short inconsistency window for changed/removed providers. This is an
operator-config error, is logged loudly, and is strictly better than the current
unconditional `clear_provider_cache` + creation race.

---

## P0 — Correctness bugs

### Task 1 — Fix error logger name
**Files**: `src/core/error_handling/error_handler.py`
- Remove `_logger = logging.getLogger("llm_router")`.
- Import `from ...core.logging import logger` and use it for both `create_error` and
  `log_provider_error` (replace `_logger.error(...)` calls; pass `exc_info` and `extra`
  via the Logger kwargs API).
**Why**: configured logger is named `nnp-llm-router` (`core/logging/config.py`);
`llm_router` has no handlers → all `create_error` logs are lost/duplicated via root.
**Validate**: `pytest tests/unit/test_error_handling.py -v`.

### Task 2 — StreamProcessor per-stream state
**Files**: `src/services/chat_service/stream_processor.py`
- Delete `self._captured_usage` instance attribute.
- Use a local `captured_usage` inside `process_stream`; pass it to
  `_record_stream_usage` and into `_sanitize_sse_message` (e.g. via a small mutable
  holder or by returning the captured usage).
- `_sanitize_sse_message` must not write to `self`.
**Why**: single shared StreamProcessor across concurrent streams overwrites
`_captured_usage` → wrong/lost usage.
**Validate**: `pytest tests/unit/test_stream_processor.py -v`; add a concurrency test
(two interleaved streams, assert each records its own usage).

### Task 3 — Provider cache race + atomic rebuild
**Files**: `src/providers/__init__.py`, `src/api/main.py`
- In `providers/__init__.py`:
  - Add module-level `_cache_lock = asyncio.Lock()`.
  - Extract `_build_provider(name, cfg, cm)` (pure factory: type dispatch only, no cache).
  - `get_provider_instance(name, cfg, cm)`: under `_cache_lock`, return cached or
    build+store.
  - Add `rebuild_provider_cache(config, cm) -> None`: acquire lock, build a temp dict by
    calling `_build_provider` for each `config["providers"]` entry (raises on first
    failure → caller handles, old cache untouched), then atomically
    `_provider_cache, old = temp, _provider_cache`; background-close old pools
    (`asyncio.ensure_future(_gather_closes(...))` when loop running).
  - Keep `clear_provider_cache_async()` for shutdown (closes + clears).
  - Inline `_close_coros`/`_gather_closes` if it simplifies (optional).
- In `main.py`:
  - Replace `_validate_providers` body to call `rebuild_provider_cache(config_manager.get_config(), config_manager)`,
    collecting per-provider failures into the startup `RuntimeError` message
    (build temp explicitly and catch per-provider exceptions, or wrap rebuild and
    reformat). Preserve eager fail-fast behavior.
  - Replace `config_manager.add_reload_callback(clear_provider_cache)` with a callback
    that calls `rebuild_provider_cache(config_manager.get_config(), config_manager)`
    (wrap so exceptions are caught + logged, do not crash the reload task).
**Why**: closes the read-create-store race (orphaned `httpx` pools) and makes reload
validate-before-clear.
**Validate**: `pytest tests/unit/test_provider_registry.py tests/unit/test_startup_validation.py -v`;
add a test: concurrent `get_provider_instance` for an uncached provider returns same
instance (no duplicate build).

### Task 4 — Usage recording: task tracking + error logging
**Files**: `src/core/usage_db.py`, `src/services/chat_service/chat_service.py`,
`src/services/embedding_service.py`, `src/services/chat_service/stream_processor.py`
- `usage_db.record_usage`: replace `except Exception: pass` with `except Exception` →
  `logger.error(...)` (include request_id, model_id, endpoint).
- Create a small helper for fire-and-forget scheduling, e.g. a module-level
  `_usage_tasks: set` in `usage_db` and `def schedule_record_usage(...)` that:
  `t = asyncio.create_task(record_usage(...)); _usage_tasks.add(t);
  t.add_done_callback(_on_usage_done)` where `_on_usage_done` logs WARNING on exception
  and discards the task from the set.
- Replace `asyncio.create_task(record_usage(...))` in chat_service (non-stream),
  embedding_service, and `_record_stream_usage` (stream_processor) with
  `schedule_record_usage(...)`.
**Why**: dropped task references can be GC'd before completion; errors are swallowed.
**Validate**: `pytest tests/unit -v` (no API test needed); unit-test the callback path
by injecting a failing record and asserting a WARNING is logged.

---

## P1 — Robustness

### Task 5 — Sanitization flag read live
**Files**: `src/services/chat_service/stream_processor.py`
- Remove `self.should_sanitize` / `_determine_sanitization_status` caching.
- In `process_stream`, read `should_sanitize = self.config_manager.should_sanitize_messages`
  (guard for `config_manager is None`).
- Keep `_message_sanitizer` class reference resolved once (lazy import is fine).
**Why**: cached flag diverges from config_manager; live read keeps behavior consistent.
**Validate**: `pytest tests/unit/test_stream_processor.py -v`.

### Task 6 — YAML top-level key validation
**Files**: `src/core/config_manager.py`
- In `_load_config`, after `safe_load`, for required files raise a clear
  `RuntimeError(f"Config file {path} missing top-level '{key}:' section")` when the
  expected top-level key is absent (don't silently coerce to `{}`).
**Why**: operator typo (flat YAML without wrapper) currently becomes empty dict and
fails only at startup assert (and not at reload).
**Validate**: `pytest tests/unit/test_config_manager.py -v`; add a test feeding a
malformed YAML and asserting the RuntimeError.

### Task 7 — Port clarification (docs only)
**Files**: `CLAUDE.md`
- Add one line under Configuration: container listens on 8000; docker-compose maps host
  8777 → container 8000; clients/tests use 8777.
**Why**: remove onboarding confusion. No code change.
**Validate**: doc review.

---

## P2 — Cleanliness / contracts

### Task 8 — Provider HTTP error factory
**Files**: `src/core/error_handling/error_handler.py`, `src/core/error_handling/__init__.py`,
`src/providers/base.py`
- Add `create_provider_http_error(status_code, message, provider_name, raw, request_id=None)`
  next to `create_error`: builds OpenRouter dict `{"error": {"code", "message",
  "metadata": {"provider_name", "raw"}}}`, logs via `core.logging.logger` with request
  context, returns `HTTPException(status_code=status_code, detail=...)`.
- Export from `error_handling/__init__.py`.
- In `base.py _raise_provider_http_error`: call `log_provider_error(...)` (keep), then
  `raise create_provider_http_error(...)` instead of hand-built `HTTPException`.
**Why**: unifies provider passthrough errors through one logging channel while keeping
dynamic status codes (enum can't encode them).
**Validate**: `pytest tests/unit/test_base_provider.py -v`.

### Task 9 — Split provider chat API
**Files**: `src/providers/base.py`, `src/providers/openai.py`,
`src/services/chat_service/chat_service.py`
- Base: replace abstract `chat_completions` with two abstract methods:
  `chat_completions(request_body, provider_model_name, model_config, request_id) -> Dict`
  and `chat_completions_stream(...) -> AsyncGenerator[bytes, None]`.
- OpenAI provider: move the `if request_body.get("stream")` branch out; non-stream body
  into `chat_completions`, stream body into `chat_completions_stream`.
- `chat_service.chat_completions`: dispatch on `request_body.get("stream")`; call
  `chat_completions_stream` → `StreamingResponse`, else `chat_completions` → JSON.
  Remove `inspect` import / `isasyncgen` check.
**Why**: explicit contract instead of runtime type sniffing.
**Validate**: `pytest tests/unit -v`; API smoke for both stream and non-stream.

### Task 10 — Service error guard contextmanager
**Files**: `src/services/base.py`, `src/services/chat_service/chat_service.py`,
`src/services/embedding_service.py`, `src/services/transcription_service.py`,
`src/services/model_service.py` (where applicable)
- Add `@contextlib.asynccontextmanager` `_guard_service_errors(self, error_ctx)` in
  `BaseService`:
  ```
  try: yield
  except HTTPException: raise
  except Exception as e:
      raise create_error(ErrorType.INTERNAL_SERVER_ERROR,
                         original_exception=e, error_details=str(e), **error_ctx)
  ```
- Replace the 3 duplicated try/except blocks in chat/embedding/transcription services
  with `async with self._guard_service_errors(error_ctx):`.
**Why**: de-duplicate identical error-wrapping pattern.
**Validate**: `pytest tests/unit -v`.

### Task 11 — Remove dead code
**Files**: `src/providers/base.py`, `src/services/embedding_service.py`,
`src/providers/openai.py`, `src/api/main.py`
- `retry_on_rate_limit`: remove `config_manager` parameter and the `elif config_manager:`
  branch (always read from `self.config_manager`); simplify config resolution.
- Remove empty `__init__` in `EmbeddingService` and `OpenAICompatibleProvider`.
- `main.py`: move `from fastapi.responses import JSONResponse` to top-level imports.
- Verify `record_usage` imports have no circular dependency (`usage_db` imports only
  `aiosqlite`); if safe, hoist the lazy `from ...core.usage_db import record_usage`
  imports to module top in services (optional — keep lazy if any doubt).
**Why**: reduce noise / dead parameters.
**Validate**: `pytest tests/unit -v`; `ruff`/lint if configured.

---

## Rollout / validation

1. After each P0 task: `python -m pytest tests/unit/ -v`.
2. After all P0–P2: full suite — `python -m pytest tests/ -v`.
3. API regression (Docker on host 8777): `docker compose up -d --build`, wait for
   `/health`, run `python -m pytest tests/api/ -v`.
4. Manual: send one streaming + one non-streaming chat completion, confirm usage row
   appears in `data/usage.db` and `/stat/api/usage`; tail logs to confirm errors now
   appear under `nnp-llm-router` logger.
5. Reload test: edit `config/providers.yaml` (add/modify a provider), wait > reload
   interval, confirm hot pickup without orphan pools; introduce a bad provider and
   confirm old cache is retained + error logged.

## Notes for implementer

- Preserve all `# ARCH:` / `# INVARIANT:` markers; update them where behavior changes.
- Follow RULES.md: no comments unless asked, English-only, semantic naming, strict types.
- Each service keeps at most the optional success-INFO per logging convention.
- Do not introduce new dependencies.
