# Tests

```
tests/
├── conftest.py              # Fixtures: base_url, api_keys, test_models, http_client
├── test_utils.py            # Helper classes for integration tests
├── transcription.ogg        # Test audio file
├── api/                     # Integration tests (require running service)
│   ├── test_connectivity.py
│   ├── test_models_endpoints.py
│   ├── test_chat_completions.py
│   ├── test_embeddings.py
│   ├── test_transcriptions.py
│   ├── test_endpoint_permissions.py
│   └── test_tools_generate_key.py
└── unit/                    # Unit tests (no external dependencies)
    ├── test_auth.py
    ├── test_base_provider.py
    ├── test_base_service.py
    ├── test_chat_service.py
    ├── test_config_manager.py
    ├── test_context.py
    ├── test_embedding_service.py
    ├── test_error_handling.py
    ├── test_logging_config.py
    ├── test_middleware.py
    ├── test_model_capabilities.py
    ├── test_model_service.py
    ├── test_provider_registry.py
    ├── test_startup_validation.py
    ├── test_stat_api_params.py
    ├── test_stream_processor.py
    ├── test_transcription_service.py
    ├── test_unhandled_exception_envelope.py
    ├── test_usage_db.py
    └── test_utilities.py
```

## Run

```bash
# One-time: a project venv matching requirements.txt. Do not rely on a shared
# interpreter — a stale httpx there fails tests over features Docker has.
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

```bash
.venv/bin/python -m pytest tests/unit/ -v   # unit tests (fast, no service needed)
.venv/bin/python -m pytest tests/api/ -v    # integration tests (service on localhost:8777)
.venv/bin/python -m pytest tests/ -v        # all
```

## Unit Tests

Не требуют запущенного сервиса. Используют моки для внешних зависимостей.

| File | What it covers |
|---|---|
| `test_auth.py` | `get_api_key` via raw ASGI (non-ASCII bearer → 401 envelope, missing/invalid key), `check_endpoint_access` (empty/unset list unrestricted, mismatch 403 + user_id logged) |
| `test_base_provider.py` | `retry_on_rate_limit` (backoff, 429 detection, config resolution), `__init__` validation, identity/static-headers fail-fast, `_get_timeout`/`_create_timeout`, concurrency semaphore + queue 503, graceful drain, late-acquisition fail-fast, header-merge parity, defaults drift tripwire, multipart retry resends audio |
| `test_base_service.py` | `_validate_and_get_config` (access check before existence — 403 before 404), model/provider resolution, `_prepare_dispatch`, identity headers |
| `test_chat_service.py` | 400 on invalid UTF-8/malformed JSON body; chat happy paths (stream + non-stream) with a stub provider |
| `test_config_manager.py` | YAML loading (success, missing file, invalid YAML), hot-reload with callbacks, property getters with env var defaults |
| `test_context.py` | `RequestContext` dataclass (`with_project_name`, `user_id`, accessor fallbacks) |
| `test_embedding_service.py` | embedding request handling over a mock provider |
| `test_error_handling.py` | `ErrorType` enum (format_message incl. placeholder strip, create_error_detail, status codes), `create_error` log level by status (4xx WARNING, 5xx ERROR), `create_provider_http_error` metadata |
| `test_logging_config.py` | logging handler wiring |
| `test_middleware.py` | Request ID injection, `X-Process-Time` header, request/response logging, POST body debug logging |
| `test_model_capabilities.py` | provider model normalization, capability merge (manual layer wins), rendering, cache load/persist |
| `test_model_service.py` | `/v1/models` listing/retrieval, hidden models, per-key access filtering |
| `test_provider_registry.py` | provider cache keyed by name, atomic rebuild, failed rebuild keeps old cache, background pool close |
| `test_startup_validation.py` | eager provider validation collects all failures and refuses to start |
| `test_stat_api_params.py` | `/stat/api` `days` query parameter contract |
| `test_stream_processor.py` | Transparent pass-through, reasoning→reasoning_content remap, usage capture, per-stream usage isolation, `[DONE]` sentinel, mid-stream error frame, `open_provider_stream` priming |
| `test_transcription_service.py` | transcription dispatch over a mock provider, default model fallback |
| `test_unhandled_exception_envelope.py` | app-level Exception handler answers in the OpenRouter envelope, one 500 stats row |
| `test_usage_db.py` | schema migration over an old DB, `RequestStats`/`set_usage`, cost freezing (per-token pricing), flush NOT NULL fallbacks, `schedule_flush` tracking, shutdown drain, summary/requests/series queries, one-row-per-request through the middleware, stat-key guard |
| `test_utilities.py` | `deep_merge` (nested, immutability), `decode_unicode_escapes` (JSON roundtrip, codec, regex fallback), `generate_key` (format, uniqueness) |

## Integration Tests

Требуют запущенного сервиса на `localhost:8777` и доступных провайдеров. Тестируют реальные HTTP-запросы.

| File | What it covers |
|---|---|
| `test_connectivity.py` | Health check, response time, concurrent requests, error handling for invalid endpoints |
| `test_models_endpoints.py` | `/v1/models` listing, `/v1/models/{id}` retrieval, hidden models, access control per API key |
| `test_chat_completions.py` | Non-streaming and streaming chat, unicode/emoji, long messages, multiple messages, auth, concurrent requests |
| `test_embeddings.py` | Embedding creation, different encoding formats, multiple inputs, auth |
| `test_transcriptions.py` | Audio transcription with/without model, response formats, concurrent requests |
| `test_endpoint_permissions.py` | Per-key endpoint access: full access, restricted, invalid key, no auth |
| `test_tools_generate_key.py` | Key generation endpoint, key format validation |

## Environment

Integration tests use `BASE_URL` env var (default `http://localhost:8777`). API keys and test models configured in `conftest.py`.
