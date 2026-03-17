# NNP AI Router

OpenAI-compatible API gateway for multiple LLM providers. One endpoint, multiple backends (OpenAI, DeepSeek, OpenRouter, Ollama, any OpenAI-compatible API).

## Endpoints

- `GET /health` — healthcheck
- `GET /v1/models` — list models (filtered by API key permissions)
- `GET /v1/models/{model_id}` — model details, enriched with live provider metadata
- `POST /v1/chat/completions` — chat completion (streaming + non-streaming)
- `POST /v1/embeddings` — text embeddings
- `POST /v1/audio/transcriptions` — speech-to-text (model optional, fallback to `DEFAULT_STT_MODEL`)
- `GET /tools/generate_key` — generate an API key in `nnp-v1-<hex>` format

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
4. **Provider layer** gets a cached provider instance (keyed by `(type, base_url)`). The provider translates the request to the backend's format (OpenAI pass-through, Anthropic Messages API, Ollama options mapping) and sends it via a shared `httpx.AsyncClient` connection pool.
5. **Streaming**: `_stream_request` yields raw bytes → `StreamProcessor` either passes them through transparently or buffers UTF-8, splits on SSE `\n\n` boundaries, and sanitizes each `data:` frame.
6. **Errors**: Provider HTTP errors are extracted from the JSON response body, logged, and returned in OpenRouter-compatible format `{"error": {"code", "message", "metadata": {"provider_name", "raw"}}}`.
7. **Rate limits**: 429 responses trigger exponential backoff retry (`min(base * 2^attempt, max)`), configurable via env vars.

## Configuration

Three YAML files in `config/`, hot-reloaded without restart (polled every `CONFIG_RELOAD_INTERVAL` seconds):

### providers.yaml — provider connections

```yaml
providers:
  deepseek:
    type: openai                          # openai | ollama | anthropic
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY         # env var name for the API key
    stream_format: sse                    # sse | ndjson
    headers:                              # extra headers (optional)
      HTTP-Referer: "https://myapp.com"
  ollama:
    type: ollama
    base_url: http://localhost:11434/api
```

`type` determines the provider class: `openai` (pass-through), `anthropic` (translates to Messages API), `ollama` (maps parameters to Ollama format). Any OpenAI-compatible API works with `type: openai`.

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
│   ├── sanitizer.py       # Strip non-standard fields (done, __stream_end__, etc.)
│   ├── error_handling/    # ErrorType enum, ErrorHandler factory, ErrorLogger
│   └── logging/           # Logger with request/response/debug_data methods
├── providers/
│   ├── __init__.py        # Provider registry with instance caching
│   ├── base.py            # Retry decorator, _make_request, _stream_request, error extraction
│   ├── openai.py          # OpenAI-compatible: chat, embeddings, transcriptions
│   ├── anthropic.py       # Translates OpenAI format → Anthropic Messages API
│   └── ollama.py          # Maps OpenAI params → Ollama options structure
├── services/
│   ├── base.py            # Model validation (access → existence → provider), provider instantiation
│   ├── chat_service/
│   │   ├── chat_service.py    # Orchestrator: validation → provider → StreamingResponse/JSONResponse
│   │   └── stream_processor.py # SSE buffering, UTF-8 split recovery, optional sanitization
│   ├── embedding_service.py
│   ├── model_service.py   # Model listing with provider enrichment
│   └── transcription_service.py  # Default model fallback
└── utils/
    ├── deep_merge.py      # Recursive dict merge (for model options)
    ├── unicode.py          # Decode \uXXXX in provider error messages
    └── generate_key.py    # nnp-v1-<64 hex chars> key generation
```

## Key Features

- **Streaming**: SSE pass-through with UTF-8 split handling at chunk boundaries. Multi-byte characters split across TCP chunks are buffered and recovered. Supports both `\n\n` and `\r\n\r\n` SSE separators.
- **Rate limit retry**: Exponential backoff on 429 — `min(base_delay * 2^attempt, max_delay)`. Detects rate limits via `status_code` and `original_exception.response.status_code`.
- **Hot-reload**: Background task polls config file mtimes. On change, reloads YAML and invokes callbacks (e.g. clearing provider cache). Partial reload (missing file) is rejected.
- **Access control**: Per-key model and endpoint restrictions. Access check runs *before* existence check to prevent leaking information about configured models.
- **Message sanitization**: When `SANITIZE_MESSAGES=true`, strips fields like `done`, `__stream_end__`, `__internal__` from messages and stream chunks. Disabled by default.
- **Provider caching**: Provider instances cached by `(type, base_url)`. Cache cleared on config reload.
- **Error format**: All errors returned as `{"error": {"code", "message", "metadata"}}` — OpenRouter-compatible. Provider errors include `metadata.provider_name` and `metadata.raw`.

## Tests

```bash
python -m pytest tests/unit/ -v   # 158 unit tests (fast, no service needed)
python -m pytest tests/api/ -v    # 114 integration tests (service on :8777)
```

See [tests/README.md](tests/README.md) for details on what each test file covers.

## Development

```bash
pip install -r requirements.txt
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HTTPX_MAX_CONNECTIONS` | 100 | Connection pool size |
| `HTTPX_MAX_KEEPALIVE_CONNECTIONS` | 20 | Keep-alive connections |
| `HTTPX_CONNECT_TIMEOUT` | 60.0 | Connection timeout (s) |
| `HTTPX_READ_TIMEOUT` | 60.0 | Provider read timeout (s) |
| `HTTPX_POOL_TIMEOUT` | 5.0 | Pool wait timeout (s) |
| `PROVIDER_MAX_RETRIES` | 3 | 429 retry attempts |
| `PROVIDER_RETRY_BASE_DELAY` | 1.0 | Retry base delay (s) |
| `PROVIDER_RETRY_MAX_DELAY` | 30.0 | Retry max delay (s) |
| `CONFIG_RELOAD_INTERVAL` | 5 | Config poll interval (s) |
| `SANITIZE_MESSAGES` | false | Strip service fields from messages |
| `LOG_LEVEL` | INFO | Logging level |
| `DEFAULT_STT_MODEL` | stt/dummy | Fallback transcription model |
