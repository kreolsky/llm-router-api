# Services & API — rules for `src/services/**`, `src/api/**`

* Services validate **access BEFORE model existence** — the order is the point: it prevents
  a caller learning which models exist from the shape of the refusal. A change to either
  check is reviewed at both layers.
* Services orchestrate: validate → resolve provider → call provider → return. No direct HTTP
  from a service; enrichment goes through `provider.list_models()`.

  ```
  Observation: $ grep -rn "get_model" src/ tests/ scripts/
               (8 "Binary file .../__pycache__/... matches" lines omitted — stale bytecode)
               tests/api/test_models_endpoints.py:234:        async def get_model(model_id: str):
               tests/api/test_models_endpoints.py:243:        tasks = [get_model(model_id) for model_id in model_ids]
               (only a same-named local test helper; the provider method was deleted)
  Rule:        enrichment goes through provider.list_models() only — get_model() is dead.
  File:        .claude/rules-scoped/services.md — tightened existing line.
  ```
* Request context is read via `core.context.request_context(request)`, which returns the
  typed `RequestContext`. Never read raw `request.state.request_id` / `project_name`, and
  never re-shape the context into a dict.
* Streaming responses use `StreamingResponse` over the service's async generator.
  `open_provider_stream` primes the first chunk BEFORE the response starts, so an upstream
  401/429 keeps its real HTTP status instead of arriving as a 200 carrying an error frame.

## Logging convention

* Prefer kwargs-style logging (`logger.info(msg, request_id=…, model=…)`). The
  `extra={...}` dict form is tolerated for backward compatibility, not for new call sites.
* The middleware Incoming/Outgoing INFO lines are the canonical per-request bookend
  (Outgoing carries `time=…ms`). Do not duplicate them in a service.
* A service MAY emit at most one optional success-INFO. `chat_service` emits none, because a
  streaming handler returns before the stream completes and a service-level "Completed" line
  would fire prematurely.
* Errors are surfaced via `create_error`, which logs them — services add no error INFO lines.
