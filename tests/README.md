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
# Unit tests (fast, no service needed)
python -m pytest tests/unit/ -v

# Integration tests (service must be running on localhost:8777)
python -m pytest tests/api/ -v

# All
python -m pytest tests/ -v
```

## Environment

Integration tests use `BASE_URL` (default `http://localhost:8777`) and API keys from `conftest.py`.
