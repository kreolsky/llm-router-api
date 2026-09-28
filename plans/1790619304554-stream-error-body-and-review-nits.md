# Stream error body reaches the client, plus audit-epic review nits

## Decisions

- Size: S, hot path (`src/providers/base.py`), so this plan file and `/review` are owed. One commit straight to `dev`. Tests: `tests/unit/` in full plus `tests/api/test_chat_completions.py`.
- Current behaviour: `_check_stream_response` (`src/providers/base.py:452`) calls `response.raise_for_status()` inside `client.stream()` without reading the body, so `_raise_provider_http_error` (`src/providers/base.py:182`) hits `httpx.ResponseNotRead` and the client receives `"Unable to read error response from provider"` as both `message` and `metadata.raw` instead of the upstream's error text. Observed live: a streaming `kimi` request answered 429 with that placeholder.
- Fix: `_check_stream_response` becomes `async`; when `response.status_code >= 400`, it `await response.aread()` before `raise_for_status()`. An `httpx.HTTPError` raised by `aread()` is suppressed, so the upstream status still surfaces and the existing `ResponseNotRead` fallback in `_raise_provider_http_error` stays the answer for an unreadable body. The call site at `src/providers/base.py:406` awaits it. Mark the read with a `WHY:` (the stream context never buffers the body; the error body is small and bounded by `stream_read_timeout`).
- `_env_bool` and `_env_number` docstrings (`src/core/config_manager.py:82`, `src/core/config_manager.py:99`) carry historical narrative ("used to read as False", "The old fallback-to-default..."); delete those sentences per `documentation.md`, keep the rest verbatim.
- The `INVARIANT:` in the `_warn_dangling_references` docstring (`src/core/config_schema.py:392`) guards a case production never reaches (its own `Why:` says so); demote it to `WHY:`, text otherwise unchanged. Code unchanged.
- `_parse_pricing` (`src/core/config_schema.py:285`) accepts `nan`, `inf` and negative values. Extend its drop rule: a price that is not finite or is negative is dropped with the same warning as an unparsable one. Update its docstring accordingly.

## Risks

- `aread()` on an upstream that sends error headers and then stalls the body holds the concurrency slot up to `stream_read_timeout`. Signal: a streaming error response that takes much longer than the headers did.
- A real model_info price of `0` must still parse (zero is valid). Signal: the `test_positive_int_parses`-style pricing tests or `/v1/models` showing a dropped free price.

## Order

1. In `src/providers/base.py`: async `_check_stream_response` with the guarded `aread()` and its `WHY:`, awaited at the call site; docstring of `_stream_request_inner` updated. In `src/core/config_manager.py`: the two docstring trims. In `src/core/config_schema.py`: the `INVARIANT:` → `WHY:` demotion and the finite/non-negative pricing rule. Tests in `tests/unit/test_base_provider.py` (MockTransport, pattern of `test_stream_429_raises_without_the_generic_error_log`): a streaming 429 with `{"error": {"message": "rate limited"}}` gives an `HTTPException` whose detail carries `"rate limited"`; a streaming 500 with a plain-text body carries that text as `raw`. Tests in `tests/unit/test_model_service.py`: pricing `nan`, `inf` and `-1e-7` each dropped with a warning; `0` kept.

## Not doing

- Changing the error envelope shape or the `create_provider_http_error` mapping.
- Retrying a streaming 429.

## Validation

- `docker compose restart api`, wait for `curl -s localhost:8777/health`. KEY is `user_keys.debug.api_key` in `config/user_keys.yaml`.
- `curl -s -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' localhost:8777/v1/chat/completions -d '{"model":"kimi","stream":true,"max_tokens":8,"messages":[{"role":"user","content":"hi"}]}'` while kimi is rate-limited: HTTP 429 whose `error.message` is the upstream's text, not the placeholder. If kimi is not rate-limited at drive time, the unit tests are the evidence and this is stated.
- One streaming and one non-streaming `deepseek/flash` request still answer 200.
