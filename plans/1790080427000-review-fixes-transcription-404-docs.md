# Review fixes: transcription refusal logging, unmatched-route envelope, marker drift

Fixes every finding from the review of `api-surface-minimization` and
`core-dedupe-fixes`. Both epics are already merged into `dev`.

## Decisions

### 1. The transcription refusal path logs its headers again

`src/api/main.py:215-220` picks `audio_file`/`file` and raises
MISSING_REQUIRED_FIELD in the ROUTE, while the header log now sits in the
service (`src/services/transcription_service.py:41-47`). A request with
neither field is refused before the service runs, so nothing about it is
logged — exactly the refusal where the headers were worth having.

- Move the selection and the raise into `TranscriptionService.create_transcription`,
  AFTER the header log. Signature gains a keyword `file: UploadFile | None = None`
  and `audio_file` becomes `UploadFile | None` — `audio_file` stays the 2nd
  positional (`tests/unit/test_transcription_service.py:73,99,127` call it that way).
- The route passes both fields through and owns no logic. Drop `ErrorType` and
  `create_error` from `src/api/main.py:14` (line 220 is their only use there);
  keep `enrich_stats_from_envelope`. Move the `# WHY:` at `src/api/main.py:205`
  (both spellings accepted) to the selection's new home.
- Tests: in `tests/unit/test_transcription_service.py`, `test_refusal_logs_headers_first`
  — call with `audio_file=None, file=None`, assert the raise AND that
  `_log_service_data` was called with `title="Transcription Request Headers"`
  before it. In `tests/api/test_transcriptions.py`, a multipart POST carrying only
  `model` → 400 with `error.metadata.error_code == "missing_required_field"`.

### 2. Unmatched routes answer in the OpenRouter envelope

`src/api/main.py:103` registers the handler on `fastapi.HTTPException`, but an
unmatched route raises `starlette.exceptions.HTTPException` — the parent class,
which a subclass key does not catch. Observed: `{"detail":"Not Found"}`. The
handler's own docstring (`src/api/main.py:110-115`) already declares the
opposite ("unmatched-route 404s ... writes only error_message"), so stats lose
`error_message` for every 404 too. The docstring states the intent — fix the code.

- Import `from starlette.exceptions import HTTPException as StarletteHTTPException`
  and use it for the decorator and the `exc` annotation. FastAPI's HTTPException
  is a subclass, so one registration covers both. Drop `HTTPException` from the
  `fastapi` import at `src/api/main.py:7` (no other use).
- `# WHY:` on the decorator: registering on the FastAPI subclass silently leaves
  router-raised 404/405 on Starlette's default `{"detail": ...}`.
- Test in `tests/unit/test_unhandled_exception_envelope.py`: derive a path no
  route matches (assert it against `app.routes`), request it, assert the body is
  `{"error": {"code": 404, "message": ...}}`. A 405 (GET on `/v1/chat/completions`)
  gets the same shape.

### 3. Marker and doc drift left by the two epics

- `src/core/model_capabilities/refresh.py:162`: `_persist_cache(cache)` runs even
  when the loop refreshed nothing (empty `models:`, or the section absent) — a
  disk write per cycle that never happened before. Guard it with `if seen:`.
- `src/core/model_capabilities/refresh.py:147`: the `# ARCH:` lives inside the
  docstring. Move it to a comment on the load-bearing line (the guarded
  `_persist_cache` call); the docstring keeps prose only.
- `tests/README.md:14`: `test_endpoint_permissions.py` is the last `api/` entry
  but kept `├──` when the line below it was deleted — make it `└──`.
- `tests/unit/test_config_manager.py:419`: drop the local
  `from src.core.config_manager import ConfigManager`; the module already imports
  it at line 8.
- `.claude/rules/workflow.md:209,221`: the home-network rule justifies itself with
  "an unrestricted `/tools/generate_key`", an endpoint deleted in
  `api-surface-minimization`. Rewrite both the rule line and the Observation block
  around `STAT_API_KEY` + the debug key's empty `allowed_endpoints` only.
  The evidence gate applies: run `grep -rn "tools/generate_key" src/` (expect
  no hits) and paste it verbatim as the Observation. **This file has uncommitted
  foreign edits** — stage only the hunks this step writes.

## Risks

- 2: every unmatched path and every 405 changes response shape for clients that
  parsed `detail`. `grep -rn '"detail"' tests/ src/` has one tolerant assertion
  (`tests/api/test_models_endpoints.py:145`, `"error" in ... or "detail" in ...`).
  A missing `/stat/static` asset also switches to the JSON envelope.
- 2: 404 rows in the usage DB start carrying `error_message`; the dashboard's
  "—" grouping for NULL `error_code` is unchanged.
- 1: the service now owns a 400 that the route used to raise; a caller of
  `create_transcription` passing neither file gets the error one frame lower.

## Order

Branch `review-fixes-round` from `dev`. The plan file ships in commit 1.

1. **1**: move the selection + raise into the service, fix the imports, two tests.
   `.venv/bin/python -m pytest tests/unit/test_transcription_service.py --tb=short`.
   Commit: `fix(transcription): the refused request logs its headers again`.
2. **2**: re-register the handler on Starlette's HTTPException, add the WHY, one test.
   `.venv/bin/python -m pytest tests/unit --tb=short`.
   Commit: `fix(errors): unmatched routes answer in the OpenRouter envelope`.
3. **3**: persist guard, ARCH placement, README connector, redundant import, rule text.
   `.venv/bin/python -m pytest tests/unit/test_model_capabilities.py tests/unit/test_config_manager.py --tb=short`.
   Commit: `docs(rules): drop the removed generate_key endpoint from the posture rule`.
4. Full suite `.venv/bin/python -m pytest tests/ --tb=short` (use `.venv`, not the
   conda env — `aiosqlite` is missing there), `.claude/scripts/pre-commit-gates.sh`
   unpiped, `git diff dev review-fixes-round --stat`, merge, delete the branch.

## Not doing

- Restoring the info-level "Transcription file received" log — deliberately
  deleted; the parameters log already carries filename, type and size.
- Making `persist()` atomic, and any further work on the two merged epics.

## Validation

- 1: `curl -s :8777/v1/audio/transcriptions -H "Authorization: Bearer dummy" -F "model=stt/dummy"`
  → 400 envelope, AND `docker compose logs --since 20s api` shows
  "Transcription Request Headers" for that request. Capture both verbatim.
- 2: `curl -s :8777/definitely-not-a-route` → `{"error":{"code":404,...}}`;
  a well-formed chat request still returns 200.
- 3: after a reload, `stat -f %m data/model_cache.json` unchanged across a cycle
  when `models:` has no providers (scratch container, `MODEL_CACHE_REFRESH_INTERVAL=5`).
- Carried from the review, never driven: empty `models:` in `config/models.yaml`
  on the live container → within 5s "Partial config reload rejected, keeping
  previous config"; restore the file. Same for the new startup refusal message
  `Configuration section(s) '...' missing or empty`.
- One `curl -N` streaming chat after the merge, frames shown.

## Progress

Not started.
