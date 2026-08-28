# Repay the 2026-08 audit debt: auth TypeError, dead timeouts, error envelope, lint gate, hygiene

## Decisions

L — the Order carries 8 commits ⇒ branch `audit-debt` from `dev`. Phases 0→5, TDD red run
required for steps 1–4. Steps 1–2 touch review-gate hot-path files (`src/core/auth.py`,
`src/providers/base.py`); per-diff entanglement is medium (3–6) ⇒ full `tests/unit/` plus the
touched `tests/api/` files after each step, repeat full-suite run before merge.

Findings were verified in the audit session (HEAD `5219f7a`, 2026-08-27); line numbers predate
this plan — locate by symbol when they drift.

1. Auth 500 on non-ASCII bearer. `src/core/auth.py:62` calls `hmac.compare_digest` on `str`,
   which requires ASCII — a bearer token with non-ASCII bytes raises TypeError ⇒ unhandled 500
   instead of 401 (reproduced in the audit session). Fix: compare UTF-8 bytes, mirroring the
   stat-key check at `src/api/main.py:261`.
2. Non-stream chat has NO read or write timeout. The root is the helper, not the call sites:
   `_create_timeout` (`src/providers/base.py:279-292`) leaves unspecified read/write as None,
   and `src/providers/openai.py:17` passes only `connect=` ⇒ a silent upstream holds its
   concurrency slot and `_inflight` until the aclose drain timeout. Decision: fix the helper —
   read/write fall back to the client's timeout the way connect/pool already do, and the
   non-stream chat call passes `read=stream_read_timeout`, the existing env knob (300s) that
   `aclose` at `src/providers/base.py:206-229` already calls "the longest a legitimate request
   may run". No new env var. The hardcoded `connect=10.0, write=10.0, pool=10.0` at
   `src/providers/openai.py:81` then simply goes away (the client defaults cover it). Also fix
   the misleading WHY at `src/core/config_manager.py:172-173` (HTTPX_READ_TIMEOUT is only the
   client-default fallback).
3. Stat `days` → 500, WITHOUT breaking the dashboard. `int(days)` at `src/api/main.py:296`
   (same pattern in the summary and requests endpoints) raises ValueError on non-numeric input
   ⇒ 500. The "All" button sends an EMPTY value (`src/static/stat.html:33`
   `<button data-days="">All</button>`), which today means "no day filter" — so a bare
   `days: int | None` would 422 that button. Keep the param a string and parse it in one
   shared helper that maps empty ⇒ None and non-numeric ⇒ 422 in the OpenRouter envelope.
   Services catch only `json.JSONDecodeError` (`src/services/chat_service/chat_service.py:33`,
   `src/services/embedding_service.py:24`) — invalid UTF-8 bodies raise UnicodeDecodeError ⇒
   500; catch `ValueError`, the common parent.
4. Unhandled exceptions bypass the error envelope: ServerErrorMiddleware answers plain-text
   "Internal Server Error". Add an `Exception` handler next to `src/api/main.py:98` returning
   the OpenRouter shape. Stats flush is unaffected — `RequestLoggerMiddleware`
   (`src/api/main.py:131`) sits BELOW ServerErrorMiddleware, so its `finally`
   (`src/api/middleware.py:146-160`) still records the row as 500.
5. Retry 429-detection at `src/providers/base.py:54`: `e.original_exception.response.status_code`
   dereferences without a None check and mixes `and`/`or` precedence — restructure with an
   explicit None guard.
6. Ruff to zero in `src/` and into the gates. 25 findings (ruff 0.16.0, pinned in
   `requirements-dev.txt`; rule set `pyproject.toml:21-22`): drop unused `Dict`/`Optional`
   (`src/providers/__init__.py:4`), sort imports (`src/services/base.py:4`),
   `contextlib.suppress` ×4, `raise … from` ×6, `zip(strict=…)` (`src/core/usage_db.py:461`),
   `dict` literals ×3; per-file-ignore B008 (FastAPI `File`/`Security` defaults,
   `src/api/main.py:172-173` and `src/core/auth.py:18`); targeted noqa+WHY for ASYNC109
   (`timeout` is the provider API param) and ASYNC230 (`src/api/stat_page.py:14` — per-request
   open keeps the HTML editable without restarts). Then REPLACE the advisory block at
   `.claude/scripts/pre-commit-gates.sh:38-44` (it counts `src tests` and carries the stale
   "~526 findings" note) with a blocking `ruff check src/`, and rewrite the same myth at
   `RULES.md:60` — with an Observation/Rule/File block whose Observation is that session's
   verbatim `ruff check src/` output.
7. Conftest dead scaffolding: session `event_loop` fixture (`tests/conftest.py:133-138`,
   legacy pytest-asyncio), path-marker block pointing at nonexistent performance/integration
   dirs (`tests/conftest.py:226-244`), unused helpers/fixtures — grep each symbol over
   `tests/` before deleting; `performance_thresholds` at `tests/conftest.py:173-181` IS used,
   keep it.
8. Hygiene: Dockerfile comment names a nonexistent SessionRegistry (`Dockerfile:18-22`) — swap
   the dead name for the real process-local singletons (CapabilitiesCache, the SQLite usage
   writer), leaving the INVARIANT's rule text verbatim; `persist()` docstring claims
   "concurrent uvicorn workers" (`src/core/model_capabilities.py:336-341`) against the
   one-worker invariant; untrack `.DS_Store` (`git rm --cached`); pin `httpx[socks]`/`aiosqlite`
   (`requirements.txt:3,5`) — a floating httpx changes the HTTP fingerprint the identity
   passthrough preserves.

## Risks

- Widening `_create_timeout` defaults touches all four call sites (chat, transcription,
  embeddings, stream). Assert the resulting `httpx.Timeout` for EACH, not only chat.
- The 300s read cap can abort a non-stream completion whose single silent gap exceeds it —
  that is what `STREAM_READ_TIMEOUT` is for (operator knob, no code change). If real lab
  workloads exceed 300s of silence, raise the env, do not revert.
- Step 3 is a client-visible contract: the dashboard's own buttons are the regression test.
- The `Exception` handler must not double-send: Starlette re-raises after the handler
  response — assert exactly one response body, driven through the ASGI app rather than
  `TestClient` (which swallows the re-raise).
- B904 `from` chains and SIM105 rewrites change log tracebacks — eyeball the diff; no batch
  `--unsafe-fixes`.
- Step 7: if removing `event_loop` breaks pytest-asyncio 1.4 loop wiring, fall back to
  pytest's default function-scoped loop rather than re-adding a session hack.
- Steps are ordered by risk (auth first); every commit is independently revertible.

## Order

1. Auth bytes compare; failing-first test: non-ASCII key ⇒ 401 envelope, not 500.
2. `_create_timeout` read/write fall back to the client; chat non-stream read=
   `stream_read_timeout`; drop the embeddings hardcodes; WHY markers; tests assert the
   `httpx.Timeout` passed by all four call sites.
3. Shared `days` parser on the three /stat/api endpoints; `except ValueError` in
   chat/embedding services; tests: `days=abc` ⇒ 422 envelope, `days=` ⇒ 200 unfiltered,
   invalid UTF-8 body ⇒ 400.
4. `Exception` handler emitting the OpenRouter envelope; test drives an unhandled error and
   asserts the JSON shape and a single response.
5. Retry-decode None guard in `base.py`; test with `original_exception.response = None`.
6. Ruff zero in `src/` (fixes + per-file-ignores + noqa/WHY), advisory block in
   `pre-commit-gates.sh` replaced by the blocking gate, RULES.md rewrite with that session's
   verbatim observation.
7. Conftest cleanup (grep-verified deletions only); suite green.
8. Doc-drift rewrites (Dockerfile, persist docstring), `git rm --cached .DS_Store`, pin
   httpx/aiosqlite; `docker compose up -d --build` so the suite runs against the pins.

## Not doing

- Upload/body-size limits — home-network posture; security-for-security's-sake is not
  attempted (workflow.md hard rule).
- The 57 ruff findings in `tests/` — the gate covers `src/` only; linting tests is a fresh
  task.
- Untracking `stat-dashboard.png` / `.material/deploy.yml` — referenced by plan history and
  possibly tooling; only `.DS_Store` goes.
- Key-scan indexing, usage-DB write batching, SYSTEMS.md stat-dashboard entry precision —
  lab scale / cosmetic.

## Validation

- After each step: full `tests/unit/` (`pytest tests/unit -q`) + touched `tests/api/` files;
  after step 8: full suite via `/run-tests` (Docker, :8777) plus a repeat run.
- Live drives on the rebuilt container, keys read from `config/user_keys.yaml` per the
  credentials hard rule: non-ASCII bearer ⇒ 401 with the JSON error envelope; streaming AND
  non-streaming chat smoke (`curl -N` and plain) with an allowed key, plus a REFUSED key for
  403; `/stat/api/summary?days=abc` ⇒ 422, `?days=7` ⇒ 200, `?days=` ⇒ 200 unfiltered, and
  the /stat/ page's own 7d/30d/90d/All buttons clicked against the running container.
- Timeout and 500-envelope steps have no live fault injection — test-level evidence is the
  stated exemption; `.claude/scripts/pre-commit-gates.sh` UNPIPED green including the new
  ruff gate.

## Progress

- [x] 1 auth · [x] 2 timeouts · [x] 3 stat/JSON robustness · [x] 4 error envelope
- [x] 5 retry guard · [x] 6 ruff gate · [x] 7 conftest · [x] 8 docs+pins · [x] validation

All steps implemented on branch `audit-debt` (session 2026-08-27); commits pending.
Validation evidence: 525 passed / 1 skipped / 10 failed (identical on repeat run; the
base `dev` build fails 12 in the same file — dead upstream `google/gemini-2.0-flash-001`
+ deepseek reasoning-token exhaustion; environmental, pre-existing). Live drives on :8777
all green: non-ASCII bearer ⇒ 401 envelope, stream + non-stream chat, refused key ⇒ 403,
stat days=7/30/90/"" ⇒ 200 and days=abc ⇒ 422 envelope. Timeout and 500-envelope steps:
no live fault injection — unit/ASGI tests are the stated exemption.
