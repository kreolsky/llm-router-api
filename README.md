# NNP AI Router

OpenAI-compatible API gateway for multiple LLM providers. One endpoint, multiple backends (OpenAI, DeepSeek, OpenRouter, Ollama, any OpenAI-compatible API).

## Endpoints

- `GET /health` — healthcheck
- `GET /v1/models` — list models (filtered by API key permissions)
- `GET /v1/models/{model_id}` — model details
- `POST /v1/chat/completions` — chat (streaming + non-streaming)
- `POST /v1/embeddings` — embeddings
- `POST /v1/audio/transcriptions` — speech-to-text
- `GET /tools/generate_key` — generate API key

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

## Configuration

Three YAML files in `config/`, hot-reloaded without restart:

### providers.yaml — provider connections

```yaml
providers:
  deepseek:
    type: openai                          # openai | ollama
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY         # env var name
  ollama:
    type: ollama
    base_url: http://localhost:11434/api
```

### models.yaml — model registry

```yaml
models:
  deepseek/chat:
    provider: deepseek
    provider_model_name: deepseek-chat    # name sent to provider API
    options:                              # merged into request body
      temperature: 0.7
  embeddings/local:
    provider: embedding
    provider_model_name: text-embedding
    is_hidden: true                       # hidden from /v1/models listing
```

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

### .env — provider API keys

```
DEEPSEEK_API_KEY=sk-...
OPENROUTER_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

## Project Structure

```
src/
├── api/              # FastAPI app, routes, middleware
├── core/
│   ├── auth.py       # API key validation, endpoint access control
│   ├── config_manager.py  # YAML config with hot-reload
│   ├── sanitizer.py  # Strip non-standard fields from messages
│   ├── error_handling/    # ErrorType, ErrorHandler, ErrorLogger
│   └── logging/      # Structured logging
├── providers/
│   ├── base.py       # Base provider: retry, streaming, error handling
│   ├── openai.py     # OpenAI-compatible provider
│   ├── anthropic.py  # Anthropic Messages API translation
│   └── ollama.py     # Ollama API mapping
├── services/
│   ├── base.py       # Model validation, provider instantiation
│   ├── chat_service/ # Chat + StreamProcessor (SSE parsing, UTF-8)
│   ├── embedding_service.py
│   ├── model_service.py
│   └── transcription_service.py
└── utils/            # deep_merge, unicode decoding, key generation
```

## Key Features

- **Streaming**: SSE pass-through with UTF-8 split handling at chunk boundaries
- **Rate limit retry**: Exponential backoff on 429 with configurable params
- **Hot-reload**: Config files monitored for changes, no restart needed
- **Access control**: Per-key model and endpoint restrictions
- **Message sanitization**: Optional stripping of non-standard service fields
- **Provider caching**: Instances cached by (type, base_url), cleared on config reload
- **Error format**: OpenRouter-compatible `{"error": {"code", "message", "metadata"}}`

## Tests

```bash
python -m pytest tests/unit/ -v   # unit tests (no service needed)
python -m pytest tests/api/ -v    # integration tests (service on :8777)
```

## Development

```bash
pip install -r requirements.txt
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HTTPX_MAX_CONNECTIONS` | 100 | Connection pool size |
| `HTTPX_READ_TIMEOUT` | 60.0 | Provider read timeout (seconds) |
| `PROVIDER_MAX_RETRIES` | 3 | 429 retry attempts |
| `PROVIDER_RETRY_BASE_DELAY` | 1.0 | Retry base delay (seconds) |
| `CONFIG_RELOAD_INTERVAL` | 5 | Config poll interval (seconds) |
| `SANITIZE_MESSAGES` | false | Strip service fields from messages |
| `LOG_LEVEL` | INFO | Logging level |
| `DEFAULT_STT_MODEL` | stt/dummy | Fallback transcription model |
