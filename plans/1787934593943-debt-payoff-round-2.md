# Debt payoff round 2: shutdown drain, pool-drain race, auth single-owner, defaults, error hygiene

L (7 commits in `## Order`) — branch `debt-payoff-round-2` from `dev`; merge back after a
green full suite.

## Decisions

- **Pending usage rows are drained, not dropped.** Shutdown runs
  `clear_provider_cache_async()` then `close_db()` (`src/api/main.py:80-81`) and never
  awaits `_usage_tasks` (`src/core/usage_db/writer.py:28`) — an in-flight `_flush_row`
  races `close_db()` and silently no-ops (the accepted-loss docstring at
  `src/core/usage_db/writer.py:318-321` covers only post-close scheduling). A
  `drain_pending_flushes(timeout)` in writer.py gathers a COPY of the set (the done
  callback mutates it), awaits with timeout, logs leftovers at WARNING, and is called
  between the two lifespan lines.
- **Late slot acquisitions fail fast once a pool starts closing.** `_acquire_slot`
  increments `_inflight` unconditionally (`src/providers/base.py:249`) and `aclose`
  (`src/providers/base.py:213-236`) only drains requests counted BEFORE `_idle` woke — a
  coroutine holding a pre-swap instance can enter after the drain waiter woke and get a
  closed pool. `aclose` sets a `_closed` flag FIRST; `_acquire_slot` checks it before
  counting and re-checks after the semaphore wait, raising SERVICE_UNAVAILABLE
  (`src/core/error_handling/error_types.py:35`) with an explicit
  `error_details="provider pool is closing"` — the template is keyed on `error_details`,
  so passing only `provider_name` leaks the raw brace. NOT PROVIDER_CONCURRENCY_LIMIT:
  `src/providers/base.py:262` already owns that code for the queue-wait timeout and the
  two causes must stay distinguishable in the stats rows. New check carries INVARIANT+Why.
- **`project_name` gets one owner: RequestContext.** `AuthContext.project_name`
  (`src/core/context.py:45`, INVARIANT at `src/core/context.py:31-36`) is read only by
  the endpoint checker's logs (`src/core/auth.py:127,133`), and its stated reason is
  stale: `get_api_key` rebuilds the request context (`src/core/auth.py:87-93`) BEFORE
  the checker's `Depends(get_api_key)` resolves. The checker switches to
  `request_context(request).user_id` (`src/core/context.py:22-24`); auth:87-93 collapses
  to the accessor + `with_project_name`; the field and the deferral note are deleted.
- **Fallback defaults live in ONE map, and a test pins it to ConfigManager.** The
  literals 60.0/300.0/3600.0/30.0 and retry 3/1.0/30.0 are duplicated between call sites
  (`src/providers/openai.py:15,19,70,89`, `src/providers/base.py:55-57,226,254,522`) and
  `_ENV_SETTINGS` (`src/core/config_manager.py:168-190`). New module-level
  `_TIMEOUT_DEFAULTS` / `_RETRY_DEFAULTS` dicts in `src/providers/base.py` keyed by the
  ConfigManager attribute names; `_get_timeout` (`src/providers/base.py:347-351`) drops
  its per-call literal arg; a drift test asserts the dicts equal the `_ENV_SETTINGS`
  defaults. Static dicts only — the env-once invariant is untouched.
- **The error envelope stops leaking placeholders and double-logging 4xx.**
  `format_message` returns the raw template on a missing kwarg — braces included — to
  the client (`src/core/error_handling/error_types.py:45-48`); the fallback strips
  `{...}` tokens instead. `create_error` logs EVERY error at ERROR
  (`src/core/error_handling/error_handler.py:35,37`), so each auth 401/403 is two lines
  (WARNING at `src/core/auth.py:41,75,124` + ERROR here); the level becomes
  `>=500 → ERROR, else WARNING`. The dead store at
  `src/core/error_handling/error_handler.py:23` (duplicate of the assignment at `src/core/error_handling/error_types.py:62`) is deleted.
- **Coverage gaps close as red-first tests, not as src changes.** Untested with no
  network need: `check_endpoint_access` (`src/core/auth.py:111-135`),
  `get_usage_data`/`get_distinct_*` (`src/core/usage_db/queries.py:49-150`), chat happy
  paths. A bug surfaced there becomes its own commit, never folded into the test commit.
- **Dead code and doc drift go in one terminal chore commit** (Order step 7) — each item
  is unreachable or stale prose with no runtime surface.

## Risks

- Dropping `AuthContext.project_name` crosses auth → services → tests. Grep BOTH the
  constructors (`AuthContext(` — `src/core/auth.py:104` + five helpers in
  `tests/unit/test_{base,model,chat,embedding,transcription}_service.py`) AND the
  attribute READS (`auth_context.project_name`, `ctx.project_name`) over `src/` and
  `tests/` — the constructor grep alone misses every assertion site.
- Steps 2-4 touch the review-gate hot path (`src/providers/base.py`, `src/core/auth.py`):
  full `tests/unit/` after each step, repeat before merge.
- Step 2 reorders `aclose`: setting `_closed` before the drain wait means requests queued
  on the semaphore during a reload now get a 503 instead of proceeding — intended, but
  the graceful-drain class in `tests/unit/test_base_provider.py` must still pass unedited.
- Step 4 changes a signature with SIX call sites, one of them on the streaming path
  (`src/providers/base.py:522`) that the unit suite may not reach — grep `_get_timeout`
  and confirm the count before editing, then drive a live stream.
- Step 5 rewrites client-visible `error.message` text and log levels: anything grepping
  `log_type: "error"` for 4xx alerts sees WARNING instead — state it in the commit body.
- func-length baseline: `_acquire_slot` grows ~6 lines (stays <50); `get_api_key` shrinks.
  No `--update` expected; if the gate disagrees, re-key with justification.
- Step 1 iterates a copy of `_usage_tasks`; the live set mutates under the done callback.

## Order

1. **fix(usage): drain pending flush tasks on shutdown** — `drain_pending_flushes()` in
   writer.py + lifespan call (`src/api/main.py:80-81`); docstring at
   `src/core/usage_db/writer.py:316-321` updated. Red first in
   `tests/unit/test_usage_db.py`: a `_flush_row` stub gated on an event, drain, assert it
   completed before close.
2. **fix(providers): fail-fast late acquisitions during pool drain** — `_closed` flag,
   checks in `_acquire_slot`, INVARIANT+Why. Red first in
   `tests/unit/test_base_provider.py`: holder keeps `_idle` clear; `aclose()` task
   waiting; second `_acquire_slot` raises 503 whose message carries no `{` token.
3. **refactor(auth): single owner for project_name** — accessor at
   `src/core/auth.py:87-93`, field drop at `src/core/context.py:45`, checker reads
   `request_context(request).user_id` (`src/core/auth.py:127,133`), five test helpers
   rewritten. `check_endpoint_access` signature unchanged.
4. **refactor(providers): one defaults map + drift tripwire** — dicts in
   `src/providers/base.py`; the `_get_timeout` signature change ripples to all six
   callers (`src/providers/openai.py:15,19,70,89`, `src/providers/base.py:226,522`);
   retry fallbacks (`src/providers/base.py:55-57`) and the queue fallback
   (`src/providers/base.py:254`) read the map;
   drift test in `tests/unit/test_base_provider.py` against `_ENV_SETTINGS`.
5. **fix(core): error envelope hygiene** — placeholder strip
   (`src/core/error_handling/error_types.py:45-48`), level-by-status
   (`src/core/error_handling/error_handler.py:35,37`), dead store out
   (`src/core/error_handling/error_handler.py:23`). Extend
   `tests/unit/test_error_handling.py`: placeholder fallback, 4xx logs WARNING, 5xx ERROR.
6. **test(unit): close no-network coverage gaps** — new cases only: endpoint checker
   (empty list ⇒ pass, mismatch ⇒ 403 envelope with user_id) in `tests/unit/test_auth.py`;
   `get_usage_data`/`get_distinct_*` over real tmp SQLite in `tests/unit/test_usage_db.py`; chat
   stream + non-stream happy paths with a stub provider in `tests/unit/test_chat_service.py`.
7. **chore: dead code and doc drift** — unreachable no-loop fallback
   (`src/providers/__init__.py:111-120`: inside an `async def`, so `get_running_loop()`
   cannot raise → unconditional `ensure_future`); dead conftest `retries` fixture
   (`tests/conftest.py:79-83`) and assert trio (`tests/conftest.py:186-215`); dead
   `tests/test_utils.py` classes (:95, :121, :221, :297, :324); RULES.md stale ruff notes
   (:60-61, :71) and the `usage_db.py` trigger (:31) → `usage_db/`; same rename in
   `.claude/rules-scoped/stat.md:1,5`, `.claude/rules/workflow.md:166`,
   `.claude/rules/documentation.md:60`; `src/core/usage_db/__init__.py:9-13` docstring
   fixed (no `_flush_row` alias exists — it is absent from the re-exports at :26-32; the
   re-exported `get_connection` is the real patch-trap); `tests/README.md` unit table.

## Not doing

- The `_build_client` no-config fallback literals (`src/providers/base.py:210`:
  connect/read 60.0, pool 5.0) stay out of the step-4 map — client-construction
  defaults, not `_get_timeout` reads. The drift test therefore covers `_get_timeout` and
  retry keys only; say so in its docstring.
- queries.py SQL refactor (f-string clauses, parallel params, positional rows —
  `src/core/usage_db/queries.py:71-150,176-291,294-381`) — its own task, before any new
  dashboard query.
- TranscriptionService onto the `_prepare_dispatch` preamble; `retrieve_model` ladder
  dedup (`src/services/model_service.py:129-146` vs `src/services/base.py:106-137`).
- `CapabilitiesCache.persist/load` off the event loop; CWD-relative `logs/`
  (`src/core/logging/config.py:56`); `UnicodeFormatter` per-line cost.
- A drift guard between conftest `api_keys`/`test_models` and server YAML; the 11
  environmental live-upstream failures (`plans/1787901000003-tech-debt-payoff.md`).
- Removing `data.pre-volume-backup/` (untracked local backup — operator's call).

## Validation

Steps 1-5: full `tests/unit/` green after each commit; `pre-commit-gates.sh` UNPIPED.
Before step 5 lands, grep `error.message` consumers (`src/static/stat.js`, `tests/`) to
confirm nothing parses the text — `metadata.error_code` is the machine-read field, the
message is human-only; if a consumer parses it, the strip stops and asks.
Live drive on a rebuilt container after steps 1-4 and 5: one chat request then
`docker compose restart api` → the row survives restart (drain); a streaming chat
(`curl -N`) with `config/providers.yaml` touched mid-stream → stream completes and the
next request succeeds (drain race + the step-4 `src/providers/base.py:522` site); allowed key 200
+ refused key 403; a 404 model and a bad upstream show the envelope with no
`{placeholder}` and one log line each.
Steps 6-7: tests + gates only; state the exemption in the commit body for step 7 doc lines.
