# NNP AI Router — Project Bible

OpenAI-compatible API gateway for multiple LLM providers. Routes requests to OpenAI, DeepSeek, OpenRouter, and any OpenAI-compatible API through a unified endpoint.

**Development rules, coding standards, and lessons: see `RULES.md`**

## Tech Stack

* **Language**: Python 3.12
* **Framework**: FastAPI 0.111.0, Uvicorn 0.29.0
* **HTTP Client**: httpx (async, connection pooling)
* **Config**: YAML (hot-reloaded every 5s)
* **Testing**: pytest, pytest-asyncio
* **Infrastructure**: Docker (python:3.12-slim), Docker Compose
* **Entry point**: `src.api.main:app`

## Core Systems

**Request Flow**: Middleware (request ID, logging) → Auth (Bearer token, HMAC) → Service (model access validation) → Provider (HTTP to backend) → Response (JSON or SSE stream).

**Provider Abstraction**: Single provider type (`openai`). Each provider instance owns its own `httpx.AsyncClient` (per-backend connection pool). Instances are cached by **provider name** (the dict key in `providers.yaml`); the cache is rebuilt on config reload, and the previous instances' pools are closed via `aclose()` **after their in-flight requests drain** (bounded by `stream_read_timeout`), so a reload never aborts a live SSE stream. Base class handles retry with exponential backoff on 429s. Optional per-provider `proxy` key (e.g. `socks5://host:port`) routes all of that provider's traffic through a SOCKS5 proxy; `None` (unset) = direct connection. Requires the `httpx[socks]` extra (`socksio`).

**Upstream Identity** (`identity:` key in `providers.yaml`, see `plans/opencode-attribution.md`): `opencode` stamps `User-Agent: opencode/<identity_version>` plus per-request `x-session-affinity`/`X-Session-Id` with a stable `ses_*` id per client project (`src/core/opencode_identity.py`, registry TTL `OPENCODE_SESSION_TTL`); `passthrough` forwards the client's whitelisted harness headers. The whitelist is data (`src/core/identity_headers.py`): the default set is `User-Agent`, `X-Session-Id`, `x-session-affinity`, `x-parent-session-id`, `anthropic-beta`, `x-stainless-*`, and a provider may **replace** it wholesale with `passthrough_headers:` in `providers.yaml` (a trailing `*` is a prefix pattern; exact names are re-cased to the configured spelling, prefix matches keep the client's). A malformed list fails fast at provider construction. Kilo Code is an opencode fork and already sends the default set (`ses_*` ids, `x-session-affinity`, `User-Agent: Kilo-Code/<v>`), so it needs `identity: passthrough` and no synthetic profile; its `HTTP-Referer`/`X-Title`/`x-kilocode-*` extras are opt-in via `passthrough_headers`. Config `headers:` and real client headers win over the synthetic profile. Stream and non-stream paths merge headers identically (`_merge_request_headers`); `Authorization` is never overwritten.

**Process Model**: **one uvicorn worker** (`API_WORKERS`, default `1`). The gateway is I/O-bound, and three subsystems are process-local singletons that extra workers would silently fork into independent copies: the OpenCode `SessionRegistry` (stable `ses_*` ids per client — the whole point of `x-session-affinity`), the `CapabilitiesCache` (N copies, N refresh loops, N× upstream polling), and the SQLite usage writer. `PRAGMA busy_timeout=5000` is set regardless so a concurrent writer waits instead of losing the event.

**Startup Validation**: Eager fail-fast — on startup every configured provider is instantiated (validating `base_url` + env API key). Any failure (collected, all reported) refuses to start.

**Request Context**: A typed `RequestContext` (`request_id`, `project_name`) frozen dataclass is stored on `request.state.request_context` by middleware and rebuilt by auth (to attach `project_name`). Services read it via `BaseService._get_request_context(request)` — no raw `request.state.request_id`/`project_name` keys.

**Configuration (YAML)**: Three files in `config/` — `providers.yaml` (connections), `models.yaml` (model registry), `user_keys.yaml` (API key access control). Hot-reloaded via background task.

**Access Control**: Per-key model restrictions. Access check runs BEFORE model existence check to prevent information leakage. Keys use `nnp-v1-<hex>` format.

**Streaming**: SSE pass-through with UTF-8 split recovery at chunk boundaries. StreamProcessor handles `\n\n` and `\r\n\r\n` separators.

**Error Format**: OpenRouter-compatible JSON with `error.code`, `error.message`, `error.metadata`.

**Message Sanitization**: Optional stripping of non-standard fields (`done`, `__stream_end__`, `__internal__`) from messages and stream chunks. Controlled by `SANITIZE_MESSAGES` env var.

**Model Capabilities**: `/v1/models` and `/v1/models/{id}` declare the full capability set per model (context, output limit, vision/modalities, supported parameters, pricing). Two layers, both in the same normalized stored shape:

1. **Manual layer** — `config/model_info.yaml` (operator-curated). Soft-validated on load: unknown keys / orphan entries (no matching model in `models.yaml`) → `logger.warning`, non-fatal.
2. **Auto-cache** — `src/core/model_capabilities.py` `CapabilitiesCache`, persisted to `data/model_cache.json`. A background task (`capabilities_refresh_loop`) calls one `list_models()` per provider, normalizes the raw upstream response (`normalize_provider_model`, shape-dispatched: OpenRouter / llama-server / generic-empty), and stores it. Stale-if-error: on upstream failure the old entry is retained.

Priority: `model_info.yaml` **always wins** over the auto-cache (deep-merge where lists are *replaced*, not concatenated — `merge_capabilities`, distinct from `utils.deep_merge`). The single serializer `render_capabilities()` produces the response shape (derives `supports_vision`, `architecture.modality`, `top_provider`, string `pricing` without exponent). The **hot path never touches the network** — `?refresh=true` is a debug-only best-effort refresh. `reasoning{}` is manual-only; upstream `supported_parameters` is not translated into it.

## Configuration (env vars)

All env-backed settings are read via `ConfigManager` **once, at construction** (`_ENV_SETTINGS`, exposed through `__getattr__`) — env vars cannot change without a restart, so per-access reads only cost the hot path a parse and moved malformed-value failures into requests. No direct `os.getenv` in providers/services except initial logger/debug setup.

**Ports**: the container listens on `8000` (uvicorn `--port 8000`); `docker-compose` maps host `8777` → container `8000`. Clients and the test suite talk to `8777`.

* **HTTPX pools**: `HTTPX_MAX_CONNECTIONS`, `HTTPX_MAX_KEEPALIVE_CONNECTIONS`, `HTTPX_CONNECT_TIMEOUT`, `HTTPX_READ_TIMEOUT`, `HTTPX_POOL_TIMEOUT` — applied **per provider pool** (each provider instance owns its own `httpx.AsyncClient`). Total connections ≈ providers × limit.
* **Streaming**: `STREAM_READ_TIMEOUT` (default 300) — read timeout for SSE streams.
* **Transcription**: `DEFAULT_STT_MODEL` (default `stt/dummy`) — fallback model when none is requested.
* **Per-provider concurrency**: optional `max_concurrent` key per provider in `providers.yaml` gates outbound requests via an `asyncio.Semaphore`; queued requests fail fast with 503 after `QUEUE_WAIT_TIMEOUT` (default `30.0`). Takes effect only after a config reload rebuilds the cache (semaphore is per-instance).
* **Upstream identity sessions**: `OPENCODE_SESSION_TTL` (default `3600`s) — idle TTL of synthetic OpenCode sessions (`identity: opencode`).
* **Model capabilities cache**: `MODEL_CACHE_ENABLED` (default `true`), `MODEL_CACHE_REFRESH_INTERVAL` (default `3600`s), `MODEL_CACHE_TTL` (default `86400`s), `MODEL_CACHE_PATH` (default `data/model_cache.json`). `data/` is mounted in `docker-compose.yml`, so the cache survives restarts.

## Architecture Discovery

Architectural decisions marked with `# ARCH:`. Constraints marked with `# INVARIANT:`. Every file has a module-level docstring.

* `grep -rn "ARCH:" src/` — all architectural decisions
* `grep -rn "INVARIANT:" src/` — constraints that must be preserved

## Design Principles

* **Thin gateway**: No business logic beyond routing. Translate formats, forward requests, return responses.
* **Provider isolation**: Each provider type handles its own format translation. Base class provides retry, HTTP, streaming.
* **Config-driven**: All provider connections, model mappings, and access control defined in YAML. No hardcoded endpoints.
* **Fail fast**: Crash on missing configs. Validate access before existence. Return clear errors.
