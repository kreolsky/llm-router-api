# Architecture Audit Remediation Plan

Implements the 10 remediation points from the architecture audit of `nnp-ai-router`.
Scope: source code in `src/` and supporting tests in `tests/unit/`.

## Decisions (locked)

1. **httpx pools** — each cached provider instance owns its own `httpx.AsyncClient`. Pool limits come from the existing global env vars (`HTTPX_MAX_CONNECTIONS`, `HTTPX_MAX_KEEPALIVE_CONNECTIONS`, `HTTPX_CONNECT_TIMEOUT`, `HTTPX_POOL_TIMEOUT`, `HTTPX_READ_TIMEOUT`) applied **per pool**. `clear_provider_cache()` calls `aclose()` on each cached client before clearing.
2. **Startup validation** — eager pass instantiates every configured provider (validates `base_url` + env API key) and asserts `providers`/`models`/`user_keys` are non-empty. Any failure raises → app refuses to start (fail-fast).
3. **ModelService routing** — add `list_models()` and `get_model(provider_model_name)` to `BaseProvider` + `OpenAICompatibleProvider`. `ModelService` calls provider methods only; no direct `client.*` HTTP.
4. **Provider cache key** — keyed by provider name (the dict key in `providers.yaml`), not `(type, base_url)`.
5. **Request context** — introduce a typed `RequestContext` dataclass replacing raw string keys on `request.state`.
6. **All env reads via `ConfigManager`** — move `STREAM_READ_TIMEOUT` (base.py) and `DEFAULT_STT_MODEL` (transcription_service.py) into `ConfigManager` properties.
7. **Logging** — kwargs-only style; remove `extra={...}` dict-style call sites; reduce duplicate INFO messages per request.
8. **Error handling** — remove the dead `except ValueError` in `BaseService._get_provider`; all errors via `create_error`.

## Out of scope

- `/tools/generate_key` endpoint — left as-is (user decision).
- Streaming error-frame ambiguity (partial response + error + `[DONE]`) — flagged in audit §2 but not in the 10-point list.
- Horizontal scaling / uvicorn workers, O(1) auth key index — not in the 10-point list.

## Affected files

- `src/providers/base.py`, `src/providers/openai.py`, `src/providers/__init__.py`
- `src/services/base.py`, `src/services/model_service.py`, `src/services/chat_service/chat_service.py`, `src/services/chat_service/stream_processor.py`, `src/services/embedding_service.py`, `src/services/transcription_service.py`
- `src/api/main.py`, `src/api/middleware.py`, `src/core/auth.py`
- `src/core/config_manager.py`, `src/core/logging/logger.py`
- `tests/unit/*` (add/update), `CLAUDE.md` (config-field docs), `RULES.md` (if conventions change)

## Ordered task list

### Phase A — Provider layer foundations (items 1, 3, 4-cache, 6-partial)

- **A1. `ConfigManager`: add new properties** for `stream_read_timeout` and `default_stt_model` (item 6). Keep existing `httpx_*` properties (now consumed per-pool by providers). Validate non-empty `providers`/`models`/`user_keys` after load (item 8).
- **A2. `BaseProvider.__init__`: own its client.** Construct an `httpx.AsyncClient` inside the provider from `ConfigManager` limits (global env applied per pool). Accept `config_manager` (already passed) and derive limits from it. Remove reliance on an externally-supplied client for transport.
- **A3. `providers/__init__.py`: key cache by provider name.** Change `get_provider_instance(provider_name, provider_config, config_manager)`; `_provider_cache: Dict[str, BaseProvider]`. `clear_provider_cache()` iterates cached instances, calls a new `aclose()` method on each, then clears (item 1 lifecycle).
- **A4. `BaseProvider.aclose()`** — close the owned `httpx.AsyncClient`.
- **A5. `BaseProvider` + `OpenAICompatibleProvider`: add `list_models()` and `get_model(provider_model_name)`** returning the provider's `/models` list / single model (item 2). Route through existing `_make_request` (GET already supported) so retry, header masking, and `_raise_provider_http_error` apply uniformly.
- **A6. `main.py` lifespan:** stop creating a shared `httpx.AsyncClient`; build `ConfigManager` then run the **eager validation pass** — instantiate every provider in `config['providers']` (this validates keys/base_urls). Any error propagates → startup fails (item 4). Remove shared client from `app.state`; services no longer receive an httpx client.

### Phase B — ModelService through providers (item 2)

- **B1. `ModelService`:** delete `_get_provider_api_details`, `_fetch_provider_models`, `_get_model_details_from_provider` (direct HTTP). Resolve the provider instance via the same path services use and call `provider.list_models()` / `provider.get_model(...)`.
- **B2.** Make `ModelService` consistent with the provider-via-cache resolution (it needs `config_manager` only now; drop `httpx_client`). Optionally inherit from `BaseService` to remove `__init__` duplication (item 4-redundancy from audit).
- **B3.** Preserve current response shapes (`_build_model_response` + provider enrichment fields: `description`, `context_length`, `architecture`, `pricing`). Keep enrichment best-effort (provider errors non-fatal → `{}`).

### Phase C — Error & cleanup (items 5, 6-rest)

- **C1. `services/base.py`:** remove the dead `except ValueError` in `_get_provider` (provider factory raises `HTTPException` via `create_error`). Confirm no other `except ValueError` depends on factory behavior.
- **C2. `base.py`:** replace inline `os.getenv("STREAM_READ_TIMEOUT", ...)` with `self.config_manager.stream_read_timeout` (item 6).
- **C3. `transcription_service.py`:** replace inline `os.getenv("DEFAULT_STT_MODEL", ...)` with `self.config_manager.default_stt_model`.

### Phase D — Typed request context (item 9)

- **D1.** New `RequestContext` dataclass (`request_id: str`, `project_name: str | None`) in `src/core/` (e.g. `src/core/context.py`).
- **D2. `middleware.py`:** create and store `RequestContext` on `request.state` under a single typed attribute; keep request-id generation.
- **D3. `auth.py`:** set `project_name` on the existing `RequestContext` (mutate or rebuild) rather than a separate raw string key. Keep constant-time comparison.
- **D4. `BaseService._get_request_context`:** read the typed `RequestContext` instead of `request.state.request_id` / `auth_data` unpacking for ids. Update all service call sites that read these.
- **D5.** Remove all raw `getattr(request.state, 'request_id'|'project_name', ...)` call sites.

### Phase E — Logging unification & noise reduction (item 7)

- **E1.** Audit all `logger.<level>(..., extra={...})` dict-style call sites (`main.py` transcription handler, `model_service.py`, others) → convert to kwargs-style.
- **E2.** Reduce duplicate per-request INFO messages: keep middleware Incoming/Outgoing + one service-level entry; drop redundant `request_context` "Started/Completed" double-logging or the service "Request:" line (pick one). Document the chosen convention in `RULES.md`.
- **E3.** Verify `Logger._process_kwargs` reserved-key prefixing still handles both paths (keep backward-compat for `extra=` if any test relies on it).

### Phase F — Config/docs/tests

- **F1. `CLAUDE.md`:** document new config fields (`stream_read_timeout`, `default_stt_model`), provider-name cache key, per-provider pool model, and the fail-fast startup behavior.
- **F2. Tests:** update/add unit tests:
  - `tests/unit/test_base_provider.py` — client ownership + `aclose()`; `list_models`/`get_model` happy path and provider-error mapping.
  - `tests/unit/test_config_manager.py` — new properties; non-empty-config rejection on reload; reload callback `aclose` behavior.
  - `tests/unit/test_model_service.py` — routing through provider mock; enrichment best-effort on provider error.
  - `tests/unit/test_base_service.py` — removed `except ValueError` path; `RequestContext` extraction.
  - `tests/unit/test_middleware.py` — typed context populated.
  - `tests/unit/test_stream_processor.py`, `test_sanitizer.py` — unchanged behavior (regression).
  - Add startup-validation test: invalid provider config / missing env key → startup raises.
- **F3.** Run full suite via the run-tests skill.

## Risks & mitigations

- **Behavior change: startup now crashes on any bad provider.** Mitigation: fail-fast is the documented principle; ensure clear error messages naming the offending provider/env var. Provide a way to see all failures (collect then raise) so operators fix multiple at once.
- **Per-provider pools increase total connections** (providers × global limit). Mitigation: documented; operators tune `HTTPX_MAX_CONNECTIONS` knowing it is now per-backend.
- **`ModelService` previously tolerated provider `/models` failures silently** — keep enrichment best-effort (return `{}` on provider error, log), do not 5xx the listing/detail endpoint.
- **Cache-key change** shifts ownership semantics; ensure `clear_provider_cache` is still the only reload hook and is registered once.
- **Hot-path refactor (RequestContext)** — touch in isolated commits; run streaming + chat tests after.

## Validation

- Unit suite green (`tests/unit/`).
- Full suite via run-tests skill (service in Docker, `/health` check).
- Manual: start with a missing provider env var → confirm crash with a clear message.
- Manual: `GET /v1/models/{id}` still enriches and degrades gracefully when a provider `/models` errors.
- Manual: streaming chat still passes through; per-provider isolation not regressed.

## Open questions for implementation

None blocking. Implementer should confirm whether `RequestContext` should be immutable (frozen dataclass, rebuild in auth) or mutable (set in middleware, update in auth) — recommend frozen + rebuild for clarity.
