# Providers — rules for `src/providers/**`

Entry file: `src/providers/base.py` (`SYSTEM: provider`), registry in
`src/providers/__init__.py` (`SYSTEM: provider-registry`). Read them before changing either.

* Every provider inherits from `BaseProvider` and implements the required interface.
* Instances are cached by **provider name** (the dict key in `providers.yaml`). Never store
  request-specific state on an instance — one instance serves every concurrent request.
* Each instance owns its own `httpx.AsyncClient` (a per-backend pool). Closing a pool
  (`aclose()`) first drains that provider's in-flight requests, so a config reload cannot
  abort a live stream. Any change to the reload/close path is driven live against an open
  SSE stream, not asserted in isolation.
* Format translation happens in the provider, never in the service layer.
* Retry lives in the base class. A provider must not implement its own.
* A new provider type needs: the class in `src/providers/`, registration in
  `src/providers/__init__.py`, and config entries in `providers.yaml` + `models.yaml`.
* Header merging is one path for streaming and non-streaming (`_merge_request_headers`).
  `Authorization` is never overwritten. Config `headers:` and real client headers win over a
  synthetic identity profile.
* Provider errors are extracted and wrapped through `create_error`, never passed through raw.

## Errors

* Every error uses the OpenRouter-compatible envelope via `create_error(ErrorType, **context)`.
* Use the `ErrorType` enum. Never hardcode a status code in a route handler.
* Log errors with request context (request_id, provider, model).
