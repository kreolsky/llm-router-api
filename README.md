# NNP AI Router

OpenAI-compatible API gateway for multiple LLM providers. One endpoint, multiple backends (OpenAI, DeepSeek, OpenRouter, any OpenAI-compatible API).

## Endpoints

- `GET /health` — healthcheck
- `GET /v1/models` — list models (filtered by API key permissions) with declared capabilities (context, vision, pricing)
- `GET /v1/models/{model_id}` — model details; `?refresh=true` for a debug best-effort upstream refresh
- `POST /v1/chat/completions` — chat completion (streaming + non-streaming)
- `POST /v1/embeddings` — text embeddings
- `POST /v1/audio/transcriptions` — speech-to-text (model optional, fallback to `DEFAULT_STT_MODEL`)
- `GET /tools/generate_key` — generate an API key in `nnp-v1-<hex>` format
- `GET /stat/` — token usage dashboard (HTML); backed by `/stat/api/users`, `/stat/api/models`, `/stat/api/usage`

## Quick Start

```bash
cp .env.example .env   # set provider API keys
docker compose up -d   # runs on localhost:8777
```

```bash
curl http://localhost:8777/v1/chat/completions \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "deepseek/chat", "messages": [{"role": "user", "content": "Hi"}]}'
```

## How It Works

1. **Request arrives** at a FastAPI endpoint. Middleware generates a `request_id` and logs the lifecycle.
2. **Auth** extracts the Bearer token, looks it up in `user_keys.yaml` (constant-time comparison), sets `project_name` on request state.
3. **Service layer** validates the model: checks `allowed_models` *before* checking existence (prevents information leakage about configured models). Resolves `provider_name` and `provider_model_name` from `models.yaml`.
4. **Provider layer** gets a cached provider instance (keyed by provider name). The provider translates the request to the backend's format and sends it via its own `httpx.AsyncClient` connection pool, optionally through a per-provider proxy.
5. **Streaming**: `_stream_request` yields raw bytes → `StreamProcessor` either passes them through transparently or buffers UTF-8, splits on SSE `\n\n` boundaries, and sanitizes each `data:` frame.
6. **Errors**: Provider HTTP errors are extracted from the JSON response body, logged, and returned in OpenRouter-compatible format `{"error": {"code", "message", "metadata": {"provider_name", "raw"}}}`.
7. **Rate limits**: 429 responses trigger exponential backoff retry (`min(base * 2^attempt, max)`), configurable via env vars.
8. **Concurrency limits**: Providers can have a `max_concurrent` cap (e.g. `3`). Requests beyond the cap wait for a slot (up to `QUEUE_WAIT_TIMEOUT` seconds); on timeout they receive an immediate 503.

## Configuration

Three YAML files in `config/`, hot-reloaded without restart (polled every `CONFIG_RELOAD_INTERVAL` seconds):

### providers.yaml — provider connections

```yaml
providers:
  deepseek:
    type: openai                          # openai
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY         # env var name for the API key
    max_concurrent: 3                     # optional: cap concurrent requests
    proxy: socks5://host:1080             # optional: route this provider's traffic through a proxy
    headers:                              # extra headers (optional)
      HTTP-Referer: "https://myapp.com"
```

`type` determines the provider class: `openai` (pass-through). Any OpenAI-compatible API works with `type: openai`. The optional `proxy` key routes all of that provider's traffic through a SOCKS5/HTTP proxy (requires the `httpx[socks]` extra); unset = direct connection.

### models.yaml — model registry

```yaml
models:
  deepseek/chat:
    provider: deepseek                    # references providers.yaml key
    provider_model_name: deepseek-chat    # name sent to provider API
    options:                              # deep-merged into request body
      temperature: 0.7
  embeddings/local:
    provider: embedding
    provider_model_name: text-embedding
    is_hidden: true                       # hidden from /v1/models listing
```

`options` are deep-merged into the request body, so you can set default parameters per model. `is_hidden` keeps the model usable but invisible in the model list.

### model_info.yaml — manual capability catalog

Declares per-model capabilities (context, output limit, vision/modalities, supported parameters, pricing). This is the **manual override** layer; the **auto-cache** (`src/core/model_capabilities.py`, persisted to `data/model_cache.json`) fills the rest from upstream `/models` responses. `model_info.yaml` always wins over the auto-cache. All fields optional.

```yaml
model_info:
  gemini/mini:
    description: "Google Gemini 2.0 Flash — fast, multimodal, tool calling"
    context_length: 1048576               # int -> top_provider.context_length too
    max_completion_tokens: 8192           # int -> top_provider.max_completion_tokens too
    architecture:
      input_modalities: [text, image]     # presence of "image" == vision (derives supports_vision)
      output_modalities: [text]
      tokenizer: Gemini                   # optional
    supported_parameters: [tools, tool_choice, max_tokens, temperature, top_p, stream]
    reasoning:                            # manual-only; not derived from upstream
      supported: false
      default_enabled: false
    pricing:                              # numbers per-token; serialized to strings (no exponent)
      prompt: 0.0000001
      completion: 0.0000004
      input_cache_read: 0.000000025
      image: 0.0000258                    # optional
```

Derived fields (`architecture.modality`, `supports_vision`, `top_provider`, string `pricing`, `per_request_limits`) are computed by `render_capabilities()` on serialization — they are **not** stored here.

### user_keys.yaml — access control

```yaml
user_keys:
  admin:
    api_key: nnp-v1-...
    allowed_models: []                    # empty = all models
    allowed_endpoints: []                 # empty = all endpoints
  restricted:
    api_key: nnp-v1-...
    allowed_models:
      - deepseek/chat
    allowed_endpoints:
      - /v1/chat/completions
```

Two levels of restriction: `allowed_endpoints` controls which API paths are accessible, `allowed_models` controls which models can be used. Empty list = unrestricted.

### .env — provider API keys and tuning

```
DEEPSEEK_API_KEY=sk-...
OPENROUTER_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

## Project Structure

```
src/
├── api/
│   ├── main.py            # FastAPI app, lifespan, routes
│   └── middleware.py       # Request ID injection, request/response logging
├── core/
│   ├── auth.py            # Bearer token extraction, hmac comparison, endpoint access
│   ├── config_manager.py  # YAML loading, hot-reload task, env-based properties
│   ├── model_capabilities.py  # Capabilities: render/normalize/merge + auto-cache + background refresh
│   ├── sanitizer.py       # Strip non-standard fields (done, __stream_end__, etc.)
│   ├── error_handling/    # ErrorType enum, ErrorHandler factory, ErrorLogger
│   └── logging/           # Logger with request/response/debug_data methods
├── providers/
│   ├── __init__.py        # Provider registry with instance caching
│   ├── base.py            # Retry decorator, _make_request, _stream_request, error extraction
│   ├── openai.py          # OpenAI-compatible: chat, embeddings, transcriptions
├── services/
│   ├── base.py            # Model validation (access → existence → provider), provider instantiation
│   ├── chat_service/
│   │   ├── chat_service.py    # Orchestrator: validation → provider → StreamingResponse/JSONResponse
│   │   └── stream_processor.py # SSE buffering, UTF-8 split recovery, optional sanitization
│   ├── embedding_service.py
│   ├── model_service.py   # Model listing/retrieval from merged capabilities (no network)
│   └── transcription_service.py  # Default model fallback
└── utils/
    ├── deep_merge.py      # Recursive dict merge (for model options)
    ├── unicode.py          # Decode \uXXXX in provider error messages
    └── generate_key.py    # nnp-v1-<64 hex chars> key generation
```

## Key Features

- **Streaming**: SSE pass-through with UTF-8 split handling at chunk boundaries. Multi-byte characters split across TCP chunks are buffered and recovered. Supports both `\n\n` and `\r\n\r\n` SSE separators.
- **Rate limit retry**: Exponential backoff on 429 — `min(base_delay * 2^attempt, max_delay)`. Detects rate limits via `status_code` and `original_exception.response.status_code`.
- **Concurrency limiting**: Per-provider `max_concurrent` (in `providers.yaml`) gates outbound requests via an `asyncio.Semaphore`. Queued requests fail fast with 503 after `QUEUE_WAIT_TIMEOUT` (default 30s).
- **Hot-reload**: Background task polls config file mtimes. On change, reloads YAML and invokes callbacks (e.g. clearing provider cache). Partial reload (missing file) is rejected.
- **Access control**: Per-key model and endpoint restrictions. Access check runs *before* existence check to prevent leaking information about configured models.
- **Message sanitization**: When `SANITIZE_MESSAGES=true`, strips fields like `done`, `__stream_end__`, `__internal__` from messages and stream chunks. Disabled by default.
- **Per-provider proxy**: Optional `proxy` key (e.g. `socks5://host:1080`) routes a provider's outbound traffic through a SOCKS5/HTTP proxy. Requires the `httpx[socks]` extra.
- **Token usage dashboard**: `/stat/` serves an HTML dashboard of token usage per user/model over time, backed by a SQLite store (`data/usage.db`, path via `USAGE_DB_PATH`). Persist it by mounting `./data:/app/data`.
- **Provider caching**: Provider instances cached by provider name (the `providers.yaml` key); each owns its own `httpx.AsyncClient` pool. Cache cleared on config reload, closing each client first.
- **Model capabilities**: `/v1/models` declares the full capability set per model (context, output limit, vision/modalities, supported parameters, pricing). Two layers — manual `model_info.yaml` (always wins) and an upstream auto-cache (`data/model_cache.json`, refreshed by a background task). The hot path never touches the network; `?refresh=true` is a debug-only best-effort refresh.
- **Error format**: All errors returned as `{"error": {"code", "message", "metadata"}}` — OpenRouter-compatible. Provider errors include `metadata.provider_name` and `metadata.raw`.

## Tests

```bash
python -m pytest tests/unit/ -v   # full unit test suite (fast, no service needed)
python -m pytest tests/api/ -v    # integration tests (service on :8777)
```

See [tests/README.md](tests/README.md) for details on what each test file covers.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HTTPX_MAX_CONNECTIONS` | 100 | Connection pool size |
| `HTTPX_MAX_KEEPALIVE_CONNECTIONS` | 20 | Keep-alive connections |
| `HTTPX_CONNECT_TIMEOUT` | 60.0 | Connection timeout (s) |
| `HTTPX_READ_TIMEOUT` | 60.0 | Non-streaming read timeout (s) |
| `HTTPX_POOL_TIMEOUT` | 5.0 | Pool wait timeout (s) |
| `STREAM_READ_TIMEOUT` | 300 | Streaming read timeout (s) |
| `OPENAI_CONNECT_TIMEOUT` | 60.0 | OpenAI connection timeout (s) |
| `OPENAI_TRANSCRIPTION_TIMEOUT` | 3600.0 | Transcription request timeout (s) |
| `OPENAI_EMBEDDINGS_READ_TIMEOUT` | 30.0 | Embeddings read timeout (s) |
| `QUEUE_WAIT_TIMEOUT` | 30.0 | Concurrency slot wait timeout (s) |
| `PROVIDER_MAX_RETRIES` | 3 | 429 retry attempts |
| `PROVIDER_RETRY_BASE_DELAY` | 1.0 | Retry base delay (s) |
| `PROVIDER_RETRY_MAX_DELAY` | 30.0 | Retry max delay (s) |
| `CONFIG_RELOAD_INTERVAL` | 5 | Config poll interval (s) |
| `MODEL_CACHE_ENABLED` | true | Populate the model capabilities auto-cache |
| `MODEL_CACHE_REFRESH_INTERVAL` | 3600 | Capabilities cache refresh interval (s) |
| `MODEL_CACHE_TTL` | 86400 | Capabilities cache entry TTL (s) |
| `MODEL_CACHE_PATH` | data/model_cache.json | Persisted capabilities cache file |
| `SANITIZE_MESSAGES` | false | Strip service fields from messages |
| `DEBUG` | false | Enable debug-level JSON logging |
| `LOG_LEVEL` | INFO | Logging level |
| `DEFAULT_STT_MODEL` | stt/dummy | Fallback transcription model |
| `USAGE_DB_PATH` | data/usage.db | SQLite path for the token usage dashboard |
