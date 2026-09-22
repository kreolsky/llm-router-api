# API surface minimization: drop duplicate logging and dead HTTP entry points

## Decisions

### A. Middleware stops intercepting request bodies

- `src/api/middleware.py:87-110`: delete the whole `if method in ("POST", "PUT",
  "PATCH") and logger.is_debug_enabled():` block, `buffered_receive`, and the
  `receive = buffered_receive` rebind. The parsed body is already logged one layer
  down by `_log_service_data` (`src/services/base.py:226` — "Chat Completion
  Request JSON", "Embedding Request JSON", "Transcription Request Parameters"),
  which is the dict the service acts on. The middleware copy is raw JSON logged twice.
- `src/api/middleware.py:17`: drop `import json` (`json.loads` at line 98 is the only use).
- `is_debug_enabled` leaves the middleware; the method stays (used at
  `src/services/chat_service/stream_processor.py:178`, `src/core/logging/logger.py:100`).
- `tests/unit/test_middleware.py:110` `test_post_body_logged_in_debug` — delete.
  `tests/unit/test_middleware.py:119` `test_post_body_not_logged_when_debug_off` —
  replace with `test_middleware_does_not_intercept_body`: debug enabled, POST `/echo`,
  `mock_logger.debug_data.assert_not_called()` — pins that this layer owns no body log.

### B. `/tools/generate_key` becomes `scripts/generate_key.py`

- `src/api/main.py:260-284`: delete the route. Delete `src/api/main.py:28`
  (`client_host`, used only at line 275) and `src/api/main.py:29` (`generate_key`,
  used only at line 278).
- Add `scripts/generate_key.py` in the style of `scripts/dump_model_info.py`: imports
  `src.utils.generate_key.generate_key`, prints one `nnp-v1-<hex>` key to stdout, never
  writes config. Docstring: paste into `config/user_keys.yaml`.
- `src/utils/generate_key.py` and `tests/unit/test_utilities.py:95-111` stay.
- Delete `tests/api/test_tools_generate_key.py`.
- Delete `tests/api/test_endpoint_permissions.py:342` (`test_limited_generate_key`,
  expects 200) and `tests/api/test_endpoint_permissions.py:446`
  (`test_transctiber_generate_key_denied`, expects 403) — both would get 404; a
  refused-principal test for a route that no longer exists has nothing to assert.
- `tests/unit/test_middleware.py:140`: remove the `"/tools/generate_key"` entry from
  `EXPECTED_ENDPOINT_NAMES` (line 168 asserts `checked >= len(...)`).
- `tests/README.md:15` and `tests/README.md:95`: remove the file's tree line and table row.

### D. Transcription route logs nothing; the service owns the logging

- `src/api/main.py:206-258` keeps only the signature, the `audio_file`/`file`
  selection + `MISSING_REQUIRED_FIELD` raise (lines 231-236), and the
  `create_transcription(...)` call. `ctx`/`request_id`/`user_id` locals (219-221) go.
- The debug header log (`src/api/main.py:223-229`) moves to the top of
  `TranscriptionService.create_transcription` (`src/services/transcription_service.py:36`),
  right after `ctx` is read and before "Transcription Request Parameters" (line 43).
  Move the import: delete `src/api/main.py:30` (`mask_headers`, only use at line 225),
  add `from ..utils.mask import mask_headers` to the service.
- The info log `Transcription file received` (`src/api/main.py:238-247`) is deleted,
  not moved: line 43's block already logs filename, content_type and file_size.
- `request_context` import at `src/api/main.py:14` stays (used at line 149).
- `tests/unit/test_transcription_service.py` has no logger assertions; the service
  signature is unchanged. `tests/api/test_transcriptions.py` asserts status codes only.

### F. Remove the dead `__main__` uvicorn entry

- `src/api/main.py:295-296` (`if __name__ == "__main__": uvicorn.run(...)`) and
  `src/api/main.py:7` (`import uvicorn`, only non-comment use). The Dockerfile CMD is
  the only entry point.

## Risks

- A: a raw-body-vs-parsed-body divergence can no longer be seen from router logs
  alone; the parsed log covers every service error path, raw bytes come from the client.
- B: any operator who minted keys over HTTP switches to the script. Historical usage
  rows with `endpoint='generate_key'` are untouched. `grep generate_key config/` is
  empty — no grant to clean up.
- D: the header debug log now carries the service's `component`, one frame lower.
- F: `python -m src.api.main` stops working; no documented run mode uses it.

## Order

Branch `api-surface-minimization` from `dev`.

1. **A**: delete the middleware block + `import json`, swap the two tests.
   `python -m pytest tests/unit/test_middleware.py --tb=short`.
   Commit: `refactor(middleware): drop duplicate debug body interception`.
2. **B**: delete route + two imports, add `scripts/generate_key.py`, delete the api
   test file and the two permission tests, fix `EXPECTED_ENDPOINT_NAMES`,
   update `tests/README.md`.
   `python -m pytest tests/unit/test_middleware.py tests/api/test_endpoint_permissions.py --tb=short`.
   Commit: `refactor(tools): move generate_key from an endpoint to a script`.
3. **D**: slim the route, move the header log + import, drop the info log.
   `python -m pytest tests/unit/test_transcription_service.py tests/api/test_transcriptions.py --tb=short`.
   Commit: `refactor(transcription): route logs nothing, service owns the logging`.
4. **F**: delete the `__main__` block + `import uvicorn`.
   `python -m pytest tests/unit/test_startup_validation.py --tb=short`.
   Commit: `chore(api): remove dead __main__ uvicorn entry`.
5. Full suite `python -m pytest tests/ --tb=short`, then
   `.claude/scripts/pre-commit-gates.sh` unpiped. Pre-merge audit
   `git diff dev api-surface-minimization --stat`, merge into `dev`, delete the branch.

## Not doing

- `cache.persist()` once per cycle and the missing-sections helper — the follow-up
  epic `core-dedupe-fixes`.
- Moving `reasoning_effort`/`reasoning_dialect` into `core/`: import churn for zero
  line savings; separate task if the layering starts to hurt.
- `/v1/models` render cache, SQLite write batching, merging the `get_summary` scans:
  YAGNI at lab load; revisit on measured pain.

## Validation

- Debug path (A, D): `LOG_LEVEL=DEBUG`, one chat POST and one multipart transcription
  through `:8777`; exactly ONE body log per request ("Chat Completion Request JSON" /
  "Transcription Request Parameters" + "Transcription Request Headers") — no
  "Request JSON", no "Transcription file received". Capture the log lines verbatim.
- Script (B): `python scripts/generate_key.py` prints one `nnp-v1-<64 hex>` key;
  `curl -s :8777/tools/generate_key -H "Authorization: Bearer <debug key>"` answers
  404 in the OpenRouter envelope.
- Streaming smoke after the merge: one `curl -N` chat stream, frames shown.
- No deploy owed; on the next routine deploy: rsync `src/` + restart, one smoke request.
