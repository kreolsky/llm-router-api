# Usage Statistics Redesign

## Context

Today stats live in `src/core/usage_db.py` (SQLite at `data/usage.db`, single `usage_events`
table) and are shown by the `/stat/` dashboard (one token chart). Gaps:

- Only successful requests that carried a `usage` block are recorded. Errors (4xx/5xx/401)
  are never recorded, so the `status_code` column is dead (always 200). Transcriptions are
  never recorded. Streams that end without a usage chunk are invisible.
- No request log, no cost, no cache-hit view, no per-client consumption totals.
- The write is fire-and-forget from 3 call sites (`chat_service`, `stream_processor`,
  `embedding_service`), each with its own field set.

## Decisions (agreed with user)

1. **Goals**: request log including errors (401 included), cost estimation, cache-hit rate
   with token detail, per-client consumption totals.
2. **Surface**: the existing `/stat/` dashboard, improved. No Prometheus.
3. **Errors**: record everything. For auth failures the user is `unknown` and the row carries
   a truncated SHA-256 hash of the presented key.
4. **Cost**: computed **at write time** from merged capabilities pricing, so historical rows
   do not drift when tariffs change. Unknown pricing → `cost_usd` NULL → UI shows "—".
5. **Retention**: keep forever, no cleanup task.
6. **`/stat/` auth**: optional `STAT_API_KEY`. When set, the JSON API requires it; the HTML
   page stays open so it can prompt for the key (see "Auth scope" below).
7. **Single write point**: the pure-ASGI `RequestLoggerMiddleware` already observes the full
   lifecycle including SSE (it returns only after the last chunk). It creates a per-request
   stats holder and flushes exactly one INSERT at the end. Services only enrich the holder.
8. **Migration**: additive `ALTER TABLE ADD COLUMN` inside `init_db()`, driven by
   `PRAGMA table_info`. Existing rows are kept and get NULL/default in the new columns.

## Schema

Additive to `usage_events` — no table rewrite, no data migration.

| Column | Type | Meaning |
| --- | --- | --- |
| `error_code` | `TEXT` | `ErrorType.code` string (`invalid_api_key`, `provider_http_error`, …), NULL on success |
| `error_message` | `TEXT` | truncated to 500 chars, NULL on success |
| `api_key_hash` | `TEXT` | first 8 hex chars of SHA-256 of the presented key, only for auth failures |
| `client_ip` | `TEXT` | |
| `reasoning_tokens` | `INTEGER NOT NULL DEFAULT 0` | from `usage.completion_tokens_details.reasoning_tokens` |
| `cost_usd` | `REAL` | NULL when pricing is unknown |
| `has_usage` | `INTEGER NOT NULL DEFAULT 1` | 0 = provider sent no usage block (stream without usage, transcription, error) |
| `stream` | `INTEGER NOT NULL DEFAULT 0` | |

New index: `idx_usage_ts ON usage_events(timestamp)` — the request log is
`ORDER BY timestamp DESC` and the existing composite index starts with `project_name`, so it
cannot serve that scan.

**Existing NOT NULL columns constrain error rows.** `project_name`, `model_id` and `endpoint`
are `NOT NULL`. A 401 knows none of them, so the flush must substitute `"unknown"` for
`project_name` and `""` for `model_id` / `provider_name`. Without this the INSERT raises and
the failure is swallowed by `record_usage`'s `except`, i.e. errors would silently not be
recorded — the exact bug this redesign exists to fix. Covered by a test.

**`has_usage` default asymmetry is intentional**: the column default is `1` so that pre-existing
rows (which always had usage) read correctly, while `RequestStats.has_usage` defaults to `0`
in Python and is set to `1` only inside `set_usage()`.

## Architecture

### Holder

New code lives in `src/core/usage_db.py`:

```
@dataclass
class RequestStats:          # mutable, stored in scope["state"]["request_stats"]
    endpoint: str = ""
    client_ip: str = ""
    model_id: str = ""
    provider_name: str = ""
    stream: bool = False
    has_usage: bool = False
    prompt_tokens / completion_tokens / cached_tokens / reasoning_tokens / total_tokens: int = 0
    error_code: str | None = None
    error_message: str | None = None
    api_key_hash: str | None = None

    def set_usage(self, usage: dict) -> None   # single token-extraction point
```

`set_usage` is the only place that reads the provider `usage` shape
(`prompt_tokens_details.cached_tokens`, `completion_tokens_details.reasoning_tokens`), so the
stream and non-stream field sets cannot drift — it replaces the role `schedule_chat_usage`
plays today.

The middleware writes into `scope["state"]`, which Starlette exposes to routes and services as
`request.state`, exactly like the existing `request_context`. Reads go through one accessor,
`usage_db.request_stats(request)`, which returns a throwaway holder when the request never
passed through the middleware (unit tests, lifespan) so no caller has to branch on `None`.

### Enrichment points

- **`src/api/middleware.py`** — creates the holder next to `RequestContext`, sets `endpoint`
  and `client_ip` up front, and flushes at the end.
- **`src/core/auth.py`** — on `MISSING_API_KEY` / `INVALID_API_KEY` writes `api_key_hash` into
  the holder before raising (it already has `request`).
- **`chat_service` / `embedding_service` / `stream_processor`** — write `model_id`,
  `provider_name`, `stream` and call `stats.set_usage(usage)`. All `schedule_chat_usage` /
  `schedule_record_usage` calls are removed and both functions deleted.
- **`stream_processor` mid-stream failures** — today a provider failure after the 200 has
  started never reaches `custom_http_exception_handler`: `process_stream` catches it,
  yields an SSE error frame and returns (stream_processor.py `_format_error`), so the row
  would read as a success (status 200, `error_code` NULL) and the error rate would be
  systematically undercounted for streams — the one error class this redesign exists to
  expose. Fix: extract the error-payload construction out of `_format_error` into a helper
  and have the `except` block write `error_code` / `error_message` into the holder from the
  same payload, so the frame and the row cannot drift (HTTPException → its
  `metadata.error_code` after step 1; any other exception → `internal_server_error`, coarse
  by design — `error_message` carries the detail). `set_usage` moves into a `finally` in
  `process_stream`, so the error path and a client disconnect keep partial usage (today the
  `except` returns before the usage schedule at the bottom).
- **`transcription_service`** — writes `model_id` / `provider_name`; tokens stay 0 and
  `has_usage` stays 0. First time transcriptions appear in stats at all.
- **`src/api/main.py` `custom_http_exception_handler`** — the single error-enrichment point.
  It already receives both `request` and `exc` for every `HTTPException`, so no raising site
  changes. It writes `error_code`, `error_message` and `provider_name` out of `exc.detail`.
  Enrichment is best-effort and must tolerate details without `metadata.error_code`: a plain
  string `detail` (unmatched-route 404s arrive as `"Not Found"`) writes only `error_message`
  and leaves `error_code` NULL. `RequestValidationError` (422) bypasses this handler
  entirely — FastAPI runs its own validation handler, but the middleware flush still writes
  the row with `status_code = 422` and `error_code` NULL. An error status with NULL
  `error_code` is an expected shape, not a bug; the UI groups it under "—".

For that to work `error_code` must be present in the detail, and today it is not:
`ErrorType.create_error_detail` (`src/core/error_handling/error_types.py`) writes only the
numeric `error.code` (the HTTP status) and adds `error.metadata` solely when `provider_name`
is passed. So the change belongs in **`error_types.py`**, not in `error_handler.py`:
`create_error_detail` always emits `error.metadata.error_code = self.code`, and
`create_provider_http_error` (`error_handler.py`) does the same with `provider_http_error`.
This is additive and OpenRouter-compatible.

### Flush

```
schedule_flush(stats, *, request_id, project_name, duration_ms, status_code, app_state)
```

Fire-and-forget through the existing `_usage_tasks` pattern (ARCH note in `usage_db.py`), so
the response is never delayed by the write. Flush tasks created during shutdown after
`close_db()` see a `None` connection and no-op — a bounded loss window at process exit,
accepted (same tolerance as today's `record_usage`).

**The flush must run in `finally`.** The current middleware wraps `await self.app(...)` in
`try / except / raise`; Starlette's `ServerErrorMiddleware` sits *outside* user middleware, so
an unhandled exception — and a `CancelledError` from a client disconnecting mid-stream —
propagates past that `except` and everything after it is skipped. Putting the flush after the
call, as the old plan assumed, silently loses exactly the 500s and aborted streams we want to
see. In `finally`, with `status_code` defaulting to 500 when no `http.response.start` was ever
sent, both cases produce a row (partial usage for a disconnect, which is accurate).

**Skip list**: `/health`, `/stat/*` (page, API and the static mount), `/docs`, `/openapi.json`,
`/favicon.ico`.

### Cost

```
cost = (prompt_tokens - cached_tokens) * price.prompt
     + cached_tokens                   * price.input_cache_read
     + completion_tokens               * price.completion
```

- Pricing comes from the merged capabilities (manual `model_info.yaml` wins over the auto-cache).
  `ModelService._resolve_stored_capabilities` is private, so add a small public
  **`ModelService.get_pricing(model_id) -> dict | None`** wrapper and call that from the flush
  instead of reaching into the underscore method. In-memory, never touches the network.
- **Missing `input_cache_read` falls back to `price.prompt`, not to 0.** Stored pricing only
  contains the keys the upstream actually sent (`normalize_provider_model`); the `"0"` filler
  exists only in the render path. Treating an absent cache rate as free would systematically
  under-report cost for every provider that does not publish one.
- **Unit invariant**: stored pricing is USD *per token* (OpenRouter's convention). Since
  `model_info.yaml` is hand-curated and a "per 1M" value would silently inflate costs by 10^6,
  state this as an `# INVARIANT:` comment next to the formula and pin it with a test.
- No pricing at all, or a zero-token event → `cost_usd` NULL. A pricing lookup failure (missing
  `model_service` on `app.state` during early lifespan included) must be caught and degrade to
  NULL, never break the flush.

## API endpoints

Unchanged: `/stat/api/users`, `/stat/api/models`, `/stat/api/usage` (token chart, same shape).

New:

- `GET /stat/api/summary?users=&models=&days=` — totals (requests, errors, error_rate, tokens
  by kind, cost, `cache_hit_rate = Σcached / Σprompt`, count of unpriced requests) plus
  breakdowns by user, model, provider, error_code and day.
  Empty selection returns zeros, not a division by zero; rows with `has_usage = 0` contribute
  0 to both sides of the ratio. Both pinned by tests.
- `GET /stat/api/requests?users=&models=&providers=&status=all|ok|error&error_code=&request_id=&days=&limit=50&offset=0`
  — newest-first request log: id, timestamp, user, model, provider, endpoint, stream, tokens,
  cost, duration_ms, status_code, error_code, error_message, api_key_hash.

### Auth scope

`STAT_API_KEY` is read via `ConfigManager` (added to `_ENV_SETTINGS`-adjacent string settings in
`_read_env_settings`, alongside `default_stt_model` — no direct `os.getenv`, per project rules).
When it is set, a `verify_stat_key` dependency requires an `X-Stat-Key` **header only** — no
`?stat_key=` query param: the logging middleware logs the full URL including the query string
(`middleware.py` builds `url = f"{path}?{query}"` before logging it), so a query-param key
would leak into request logs. When unset, everything stays open as today.

The guard covers **`/stat/api/*` only**:

- `GET /stat/` must stay open, otherwise the page that prompts for the key can never load.
- `/stat/static` is an `app.mount(StaticFiles(...))`, and a `Depends` cannot be attached to a
  mount at all.

Consequence worth stating plainly: with `STAT_API_KEY` unset, the new request log — which
exposes per-client models, IPs and upstream error text — is as public as the current chart.
That is the accepted trade-off; operators who care set the key.

## Dashboard UI

Rewrite of `src/static/stat.{html,js,css}`, same stack (vanilla JS + Chart.js from CDN,
existing `stat.css` conventions):

1. **Summary cards** for the current filters: requests, error rate, prompt / cached /
   completion / reasoning tokens, cache-hit rate, cost with an "N requests unpriced" note.
2. **Tables**: per-user (requests, tokens, cost — this is the "which clients consume what"
   answer), per-model, per-provider.
3. **Token chart**: the existing stacked daily chart, unchanged.
4. **Request log**: server-side paginated table with filters (user, model, status, error_code,
   request_id search), colour-coded status, row expansion for `error_message`.
5. Shared user / model / period filters across all sections; key prompt stored in
   `localStorage` when the API answers 401.

Old rows have NULL `cost_usd` / `error_code`: render `—` and exclude them from cost sums rather
than coercing to 0. NULL `error_code` is not only old rows — 422s, disconnects before a
response start and any error path that bypassed the enrichment point land there too; group
NULL as a single `—` bucket in the error_code breakdown (and in the request-log filter),
rather than scattering empty cells.

## Task order (TDD — RULES.md)

1. **`error_types.py` / `error_handler.py`**: `metadata.error_code`. Independent of everything
   else and safe to land first; update `tests/unit/test_error_handling.py`.
2. **Tests first for `usage_db`**: migration over an existing DB, `set_usage` extraction,
   cost math (priced / unpriced / cached / missing `input_cache_read`), NOT NULL fallbacks for
   error rows, error-row variants (auth 401 with key hash, handler 4xx with dict detail,
   string-detail 404, 422 bypass with NULL `error_code`, mid-stream SSE error with partial
   usage), summary + requests queries (filters, pagination, cache_hit_rate, empty range,
   error grouping including the NULL bucket). `tests/unit/test_usage_db.py` currently tests
   `schedule_chat_usage` / `schedule_record_usage` — those tests are rewritten here, not left
   dangling.
3. **One commit, indivisible** — `usage_db.py` (holder, `set_usage`, flush, cost, migration,
   queries; delete the old schedulers) + `middleware.py` (holder, endpoint naming, skip list,
   `finally` flush) + `main.py` exception-handler enrichment + `auth.py` key hash + all four
   services, including the `stream_processor` error-frame enrichment and the
   `_format_error` helper extraction. Splitting it means a window where the middleware
   writes while the old call sites still write: every chat request double-counted.
4. **`ModelService.get_pricing`** with its test (can land with step 3 if convenient).
5. **`config_manager.py`** `STAT_API_KEY`, `verify_stat_key`, and the `/stat/api/summary` +
   `/stat/api/requests` routes in `main.py`.
6. **Static dashboard rewrite.**
7. **Verification**: `python -m pytest tests/ -v`, then a docker rebuild and a manual pass over
   the real `data/usage.db` — old rows must still render, a live SSE request on :8777 must
   produce exactly one row with tokens, an aborted SSE request must produce one partial-usage
   row, and a bad API key must produce a 401 row with the key hash and `unknown` user.

Reuse in passing: `main.py` already has `_client_host(request)`. Move it to `src/utils/` and
call it from the middleware rather than writing a second client-address parser, and extend it
to prefer the leftmost `X-Forwarded-For` entry when present: in production the gateway sits
behind a reverse proxy and `request.client.host` would record the proxy's address on every
row. The header is client-spoofable when no proxy strips it — acceptable because
`client_ip` is informational stats, never auth.

## Risks

- **Stream flush ordering**: usage must reach the holder before `app()` returns. Starlette
  fully consumes the response generator before returning, so it does; on a client disconnect
  the propagation path is cancellation into the generator's `finally` (`set_usage` lives
  there), which also completes before the middleware's `finally` runs — verify both with an
  integration test against :8777 rather than trusting the reasoning.
- **Mid-stream error classification**: depends on the `_format_error` helper extraction; if
  the SSE frame and the holder enrichment ever drift apart, stream failures silently read as
  successes again. Pinned by the mid-stream error test in step 2.
- **Exactly one flush per request**: the middleware is the only writer. Guaranteed only if
  step 3 stays one commit.
- **Public error shape**: `metadata.error_code` is additive, but confirm no client asserts an
  exact set of metadata keys.
- **Lifespan ordering**: the flush reads `app.state.model_service`; it must tolerate its
  absence.
- **Cost credibility**: a wrong pricing unit is invisible in the UI and poisons every historical
  row, since costs are frozen at write time. Hence the invariant + test.

## Out of scope

Prometheus/Grafana, latency percentiles and TTFT, provider retry counts, retention/cleanup,
storing message content, auto-injecting `stream_options.include_usage`.
