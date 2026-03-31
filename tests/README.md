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
    ├── test_stream_processor.py
    ├── test_base_provider.py
    ├── test_error_handling.py
    ├── test_config_manager.py
    ├── test_sanitizer.py
    ├── test_utilities.py
    ├── test_base_service.py
    └── test_middleware.py
```

## Run

```bash
python -m pytest tests/unit/ -v   # unit tests (fast, no service needed)
python -m pytest tests/api/ -v    # integration tests (service on localhost:8777)
python -m pytest tests/ -v        # all
```

## Unit Tests

Не требуют запущенного сервиса. Используют моки для внешних зависимостей.

| File | What it covers |
|---|---|
| `test_stream_processor.py` | SSE parsing (`\n\n`, `\r\n\r\n`), UTF-8 split at chunk boundary, sanitization mode vs transparent pass-through, `[DONE]` sentinel, comment lines, `_format_error` |
| `test_base_provider.py` | `retry_on_rate_limit` decorator (exponential backoff, 429 detection, config resolution), `__init__` validation (missing base_url/api_key), `_apply_model_config`, `_raise_provider_http_error` |
| `test_error_handling.py` | `ErrorType` enum (format_message, create_error_detail, status codes), `ErrorContext.to_log_extra`, all `ErrorHandler.handle_*` methods and returned HTTP status codes |
| `test_config_manager.py` | YAML loading (success, missing file, invalid YAML), hot-reload with callbacks, property getters with env var defaults |
| `test_sanitizer.py` | `sanitize_messages` (SERVICE_FIELDS removal, immutability), `sanitize_stream_chunk` (delta/choice level), `_sanitize_dict` (nested dicts, lists) |
| `test_utilities.py` | `deep_merge` (nested, immutability), `decode_unicode_escapes` (JSON roundtrip, codec, regex fallback), `generate_key` (format, uniqueness) |
| `test_base_service.py` | `_validate_and_get_config` (access check before existence — 403 before 404), model/provider resolution, `_get_request_context` |
| `test_middleware.py` | Request ID injection, `X-Process-Time` header, request/response logging, POST body debug logging |

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
