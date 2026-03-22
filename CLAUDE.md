# NNP AI Router — Project Bible

OpenAI-compatible API gateway for multiple LLM providers. Routes requests to OpenAI, DeepSeek, Anthropic, OpenRouter, Ollama, and any OpenAI-compatible API through a unified endpoint.

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

**Provider Abstraction**: Three provider types (`openai`, `anthropic`, `ollama`). Instances cached by `(type, base_url)`, cache cleared on config reload. Base class handles retry with exponential backoff on 429s.

**Configuration (YAML)**: Three files in `config/` — `providers.yaml` (connections), `models.yaml` (model registry), `user_keys.yaml` (API key access control). Hot-reloaded via background task.

**Access Control**: Per-key model restrictions. Access check runs BEFORE model existence check to prevent information leakage. Keys use `nnp-v1-<hex>` format.

**Streaming**: SSE pass-through with UTF-8 split recovery at chunk boundaries. StreamProcessor handles `\n\n` and `\r\n\r\n` separators.

**Error Format**: OpenRouter-compatible JSON with `error.code`, `error.message`, `error.metadata`.

**Message Sanitization**: Optional stripping of non-standard fields (`done`, `__stream_end__`, `__internal__`) from messages and stream chunks. Controlled by `SANITIZE_MESSAGES` env var.

## Architecture Discovery

Architectural decisions marked with `# ARCH:`. Constraints marked with `# INVARIANT:`. Every file has a module-level docstring.

* `grep -rn "ARCH:" src/` — all architectural decisions
* `grep -rn "INVARIANT:" src/` — constraints that must be preserved

## Design Principles

* **Thin gateway**: No business logic beyond routing. Translate formats, forward requests, return responses.
* **Provider isolation**: Each provider type handles its own format translation. Base class provides retry, HTTP, streaming.
* **Config-driven**: All provider connections, model mappings, and access control defined in YAML. No hardcoded endpoints.
* **Fail fast**: Crash on missing configs. Validate access before existence. Return clear errors.
