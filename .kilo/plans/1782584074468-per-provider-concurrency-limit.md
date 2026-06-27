# Plan: Per-provider concurrency limit (queue) for `orange`

## Goal
Protect the local provider `orange` (10.10.1.20:5010) from overload by limiting the number of
in-flight requests to it. Requests beyond the limit are **queued**; if a request waits longer
than a timeout, it fails fast with 503 instead of hanging the client.

## Problem
`httpx.Limits` caps only TCP connections in the pool and turns excess into `PoolTimeout` → 503.
It does **not** queue requests, and within the limit all requests still hit upstream, which then
returns 502 when overloaded. We need an `asyncio.Semaphore` that gates **all outbound calls** to a
provider and holds the slot for the full request lifecycle (including streaming).

## Decisions (resolved)
- **Scope**: per-provider. Configured via a `max_concurrent` key in `providers.yaml`; only `orange`
  sets it. Providers without the key behave as today (no limit).
- **Queue behavior**: requests beyond the limit wait on the semaphore up to `QUEUE_WAIT_TIMEOUT`
  seconds; on timeout → 503 `SERVICE_UNAVAILABLE`.
- **Slot lifetime**: held across the entire request, including stream consumption (acquire on stream
  start, release when the async generator finishes/closes).

## Affected boundaries
- `src/providers/base.py` — `BaseProvider.__init__`, new `_acquire_slot()` ctx mgr, wrap `_make_request`
  and `_stream_request`.
- `src/core/config_manager.py` — new `queue_wait_timeout` property (env `QUEUE_WAIT_TIMEOUT`, default `30.0`).
- `config/providers.yaml` — add `max_concurrent: 2` under `orange`.
- `tests/unit/test_base_provider.py` — add tests for limit, queue, timeout, and stream release.
- Docs: update `CLAUDE.md` Configuration section with `QUEUE_WAIT_TIMEOUT`.

## Implementation tasks

### 1. `BaseProvider.__init__` — create per-instance semaphore
In `src/providers/base.py`, after `self.client = self._build_client()`:
- Read `max_concurrent = config.get("max_concurrent")`.
- If it's a positive int → `self._semaphore = asyncio.Semaphore(int(max_concurrent))` and
  `self._max_concurrent = int(max_concurrent)`.
- Else → `self._semaphore = None` and `self._max_concurrent = None` (no limiting).
- Log at info which mode is active (component `base_provider`).
- Note: `asyncio.Semaphore()` in `__init__` is fine; instances are created inside the running loop
  (startup validation, `get_provider_instance`).

### 2. `_acquire_slot(request_id)` async context manager
New method returning an `@contextlib.asynccontextmanager`:
- If `self._semaphore is None` → `yield` immediately (no-op).
- Else `wait = self.config_manager.queue_wait_timeout`; do
  `await asyncio.wait_for(self._semaphore.acquire(), timeout=wait)` inside try; `yield`; finally
  `self._semaphore.release()`.
- On `asyncio.TimeoutError` → raise `create_error(ErrorType.SERVICE_UNAVAILABLE,
  error_details="Concurrency limit reached for provider; retry later.",
  request_id=request_id, provider_name=self.provider_name)`.
- Acquire/release must be exception-safe (the `finally` always releases if acquired).

### 3. Wrap `_make_request` (non-stream)
`_make_request` is decorated with `@retry_on_rate_limit`. Keep that decorator on the outer method,
and add an inner wrapper: rename the current body to `_make_request_inner` (keep its decorator) and
make the public `_make_request` do `async with self._acquire_slot(request_id): return await
self._make_request_inner(...)`. This ensures the retry loop happens **inside** the held slot (one slot
per logical request, retries reuse it) and the slot is released exactly once per call.

### 4. Wrap `_stream_request` (stream)
`_stream_request` is an `async def` generator (it `yield`s chunks). Acquiring the slot must cover the
**entire** iteration by the downstream consumer (`stream_processor.process_stream`), not just method
entry. Implement as an async-generator wrapper around the current generator:
- Keep current logic in `_stream_request_inner(...)`.
- New `_stream_request(...)` signature unchanged:
  ```
  async with self._acquire_slot(request_id):
      async for chunk in self._stream_request_inner(client, url_path, request_body, request_id):
          yield chunk
  ```
  `async with` releases on normal completion, on exception, and on generator close (AClose) — so
  client disconnect also frees the slot.

### 5. `ConfigManager.queue_wait_timeout`
In `src/core/config_manager.py` add:
```
@property
def queue_wait_timeout(self) -> float:
    return float(os.getenv("QUEUE_WAIT_TIMEOUT", "30.0"))
```

### 6. `config/providers.yaml`
Under `orange` add:
```
    max_concurrent: 2
```
Leave all other providers unchanged.

### 7. Tests (`tests/unit/test_base_provider.py`)
Reuse `ProviderStub`/`_make_config`. Add:
- **No limit when unset**: provider without `max_concurrent` → `_semaphore is None`, requests run
  concurrently.
- **Limit enforced (non-stream)**: `max_concurrent: 1`, two concurrent `_make_request` calls using
  mocked `self.client.post` with a gate event → second waits; after first resolves, second proceeds.
- **Queue timeout → 503**: `max_concurrent: 1`, `queue_wait_timeout` very small (monkeypatch config
  mgr property), first call blocks on event → second raises `HTTPException(503)`.
- **Stream slot released on completion**: `max_concurrent: 1`, run a stream gen to completion, then a
  second stream gen must start immediately (slot was released).
- **Stream slot released on early close / exception**: `aclose()` the generator mid-stream or raise
  inside → next request acquires immediately (verify `release` semantics).
- **Retry stays within slot**: simulate a 429 then success on `_make_request` and assert the slot is
  held across both attempts (semaphore value stays 0 during retry).

## Risks / invariants to preserve
- **INVARIANT** in `base.py`: `Authorization` header set once in `__init__` — unchanged.
- **ARCH**: cache key = provider name; semaphore is per-instance so a config reload that bumps
  `max_concurrent` takes effect only after `clear_provider_cache()` (document this).
- Slot leak risk: every `acquire` MUST pair with `release`. Use `async with`/`finally`, never bare
  acquire without try/finally. Tests cover exception + close paths.
- `asyncio.wait_for` on `acquire` does not acquire on timeout (verified by behavior); confirm no
  double-release in tests.

## Validation
- `pytest tests/unit/test_base_provider.py` (new + existing pass).
- Full suite via run-tests skill.
- Manual: send 3 parallel streaming requests to an `orange` model; expect 2 active + 1 queued, no 502,
  and 503 if `QUEUE_WAIT_TIMEOUT` is exceeded (set a low value to trigger).
- Confirm `deepseek`/`kimi`/others (no `max_concurrent`) behave unchanged (no semaphore).
