# Usage Statistics Redesign

## Context

Current stats: `src/core/usage_db.py` (SQLite `data/usage.db`, one `usage_events` table) + `/stat/` dashboard (one token chart). Gaps:

- Only successful requests with a `usage` block are recorded. Errors (4xx/5xx/401) never recorded; `status_code` column is dead (always 200). Transcriptions never recorded. Streams without a usage chunk are invisible.
- No request log, no cost, no cache-hit-rate view, no per-user summary.
- Fire-and-forget write scattered across 3 call sites (chat_service, stream_processor ×2, embedding_service).

## Decisions (agreed with user)

1. **Goals**: request log with errors (incl. 401), cost estimation, cache hit rate + token details, per-client consumption totals.
2. **Surface**: improved `/stat/` dashboard only. No Prometheus.
3. **Errors**: record everything, including 401 with `user="unknown"` + truncated SHA-256 key hash.
4. **Cost**: computed **at write time** from merged capabilities pricing (model_info.yaml wins over auto-cache — `ModelService._resolve_stored_capabilities`). Historical costs don't drift when tariffs change. No pricing → `cost_usd` NULL → UI shows "unknown".
5. **Retention**: keep forever. No cleanup task.
6. **/stat/ auth**: optional env `STAT_API_KEY`. If set → `/stat/*` requires `X-Stat-Key` header or `?stat_key=` query param; dashboard prompts and stores in localStorage. If unset → open as now.
7. **Single write point**: pure-ASGI `RequestLoggerMiddleware` already observes the full lifecycle (incl. SSE streams — it returns after the last chunk). It creates a per-request stats holder and flushes exactly one INSERT at response end. Services only enrich the holder.
8. **Migration**: additive `ALTER TABLE ADD COLUMN` on `init_db()` (idempotent, tolerate "duplicate column"). Existing rows kept; old rows get NULLs in new columns.

## Schema (additive to `usage_events`)

New columns:

- `error_code TEXT` — ErrorType string code (`invalid_api_key`, `provider_http_error`, …) or passthrough code
- `error_message TEXT` — truncated to 500 chars, NULL on success
- `api_key_hash TEXT` — first 8 hex chars of SHA-256, only for auth failures
- `client_ip TEXT`
- `reasoning_tokens INTEGER NOT NULL DEFAULT 0` — from `usage.completion_tokens_details.reasoning_tokens`
- `cost_usd REAL` — NULL when no pricing known
- `has_usage INTEGER NOT NULL DEFAULT 1` — 0 = provider sent no usage block (stream w/o usage, transcription)
- `stream INTEGER NOT NULL DEFAULT 0`

New index: `idx_usage_ts ON usage_events(timestamp)` (request log `ORDER BY timestamp DESC`).

## Architecture

**Holder + enrich + flush** (new code lives in `src/core/usage_db.py`, extended):

```
RequestStats dataclass (mutable, on request.state.stats)
  fields: user, model, provider, endpoint, stream, has_usage,
          prompt/completion/cached/reasoning/total_tokens, error_code,
          error_message, api_key_hash, client_ip
```

Enrichment points (write to holder, never to DB):

- `middleware.py`: creates holder + RequestContext; sets endpoint name + client_ip at start; after `await self.app(...)` returns (stream fully sent) computes duration and calls `schedule_flush(stats, request_id, duration_ms, status_code, app_state)`. Skips `/health`, `/stat/*`, `/docs`, `/openapi.json`, `/favicon.ico`.
- `auth.py`: on `MISSING_API_KEY`/`INVALID_API_KEY` writes `api_key_hash` into holder before raising (has `request`).
- `chat_service` / `embedding_service` / `stream_processor`: write model/provider/stream + tokens into holder (replaces all `schedule_chat_usage`/`schedule_record_usage` calls — those functions are deleted). Shared token-extraction helper `stats.set_usage(usage_dict)` kept in one place so stream/non-stream field sets cannot drift.
- `transcription_service`: writes model/provider (tokens stay 0, `has_usage=0`) — first time transcriptions are counted.
- `error_handler.create_error` + `create_provider_http_error`: add `metadata.error_code = <string code>` (+ provider_name already there for provider errors). `custom_http_exception_handler` in `main.py` (sees request + exc for every HTTPException) writes `error_code`/`error_message`/`provider_name` from `exc.detail` into the holder. This is the single error-enrichment point — no changes to raising sites.

Flush (in usage_db): fire-and-forget task (existing `_usage_tasks` ARCH pattern). Resolves pricing via `app_state.model_service._resolve_stored_capabilities(model_id)` (in-memory, no network) and computes:

```
cost = (prompt - cached) * pricing.prompt
     + cached * pricing.input_cache_read
     + completion * pricing.completion
```

Missing pricing or zero-token events → `cost_usd` NULL. Failed pricing lookup must never break the flush.

**Client disconnect mid-stream**: Starlette cancels the generator; `app()` still returns → flush fires with partial usage. Crash mid-stream → no event (acceptable).

## API endpoints

Keep: `/stat/api/users`, `/stat/api/models`, `/stat/api/usage` (token chart data, unchanged shape).

New:

- `GET /stat/api/summary?users=&models=&days=` — totals (requests, errors, error_rate, tokens by kind, cost, cache_hit_rate = Σcached/Σprompt, unpriced count) + breakdowns: by user, by model, by provider, by error_code, by day (for chart).
- `GET /stat/api/requests?users=&models=&providers=&status=all|ok|error&error_code=&request_id=&days=&limit=50&offset=0` — request log rows newest-first (id, timestamp, user, model, provider, endpoint, stream, tokens, cost, duration_ms, status_code, error_code, error_message, api_key_hash).

All `/stat/*` routes go through a `verify_stat_key` dependency reading `STAT_API_KEY` from ConfigManager (`config_manager.py` property, env-backed, per project rules — no direct `os.getenv`).

## Dashboard UI (`src/static/stat.{html,js,css}` rewrite)

Same stack (vanilla JS + Chart.js from CDN, follow existing `stat.css` conventions):

1. **Summary cards** for selected period/filters: requests, error rate, prompt/cached/completion/reasoning tokens, cache hit rate, cost (+ "N requests unpriced" note).
2. **Tables**: per-user (requests, tokens, cost — answers "какие клиенты сколько потребляют"), per-model, per-provider.
3. **Tokens chart**: existing stacked daily chart, kept as-is.
4. **Request log**: server-side paginated table, filters (user, model, status ok/error, error_code, request_id search); color-coded status; row detail expands error_message.
5. Existing user/model/period filters shared by all sections. Key prompt for `STAT_API_KEY` mode (localStorage).

## Task order (TDD — RULES.md)

1. **Tests first** for usage_db: schema migration on existing DB, `set_usage` extraction (incl. `prompt_tokens_details.cached_tokens`, `completion_tokens_details.reasoning_tokens`), cost calc (priced / unpriced / cached math), summary + requests queries (filters, pagination, cache_hit_rate, error grouping).
2. `usage_db.py`: RequestStats holder, `set_usage`, flush + cost, migration, new queries; delete `schedule_chat_usage`/`schedule_record_usage`/old per-service paths.
3. `middleware.py`: holder creation, endpoint naming, skip-list, flush call.
4. `error_handler.py` metadata `error_code`; `main.py` exception-handler enrichment; `auth.py` key-hash enrichment.
5. Services + `stream_processor.py`: holder enrichment only (transcription added).
6. `config_manager.py`: `STAT_API_KEY` property; `/stat/*` guard dependency; new `/stat/api/summary`, `/stat/api/requests` routes in `main.py`.
7. Static dashboard rewrite.
8. Full test suite (`python -m pytest tests/ -v`), then docker rebuild + verify against real `data/usage.db` (old rows still render).

## Risks

- **Stream flush ordering**: usage must land in the holder before `app()` returns (Starlette fully consumes the generator first). Verify with an integration test on :8777.
- **Public error shape change**: additive `metadata.error_code` — harmless for OpenRouter compat, but verify no client asserts exact metadata keys.
- **Middleware knows model_service**: pricing lookup goes through `app.state`; guard against lifespan ordering (stats flush must tolerate missing `model_service`).
- **Old rows**: `cost_usd`/`error_code` NULL — UI must render "—" / exclude from cost sums.
- **Duplicate events**: exactly one flush per request (middleware is the only writer). Remove old call sites in the same commit — a leftover `schedule_chat_usage` call would double-count.

## Out of scope

- Prometheus/Grafana metrics, latency percentiles/TTFT, provider retry counts, retention/cleanup, storing message content, auto-injecting `stream_options.include_usage`.
