# Tech-debt payoff: retry safety, auth contract, module splits

## Decisions

- **Retry must not consume the upload.** `src/providers/openai.py:63` builds one
  `io.BytesIO` and hands it to `_make_request`; the retry loop sits below, on
  `_make_request_inner` (`src/providers/base.py:406`), so a 429 replays the POST with a
  file object already at EOF. Fix at the construction site: pass raw `bytes` to httpx
  (`audio["data"]` already is bytes) rather than seeking inside the retry — the provider
  layer must stay unaware of upload rewinding.
- **Background closes are tracked like usage flushes.** `src/providers/__init__.py:104`
  drops the `ensure_future` result, so the drain task is collectable before it closes the
  old pools. Reuse the pattern already proven in `src/core/usage_db.py:322` (module-level
  set + done callback), not a new abstraction.
- **`auth_data` becomes a frozen dataclass.** The positional 4-tuple is unpacked at four
  sites (`src/services/base.py:88`, `src/services/model_service.py:101` and `:128`,
  `src/core/auth.py:115`) plus its construction in `get_api_key`, and its second element is
  dead: `src/services/base.py:88` binds `api_key` and never reads it; nothing in `src/` reads index 1.
  `AuthContext(project_name, allowed_models, allowed_endpoints)` mirrors the
  `RequestContext` refactor. `project_name` stays on it for `endpoint_checker`'s logs even
  though `RequestContext` also carries it — one owner per contract is a separate task.
- **`usage_db` splits along the seam it already has.** Writer and dashboard queries share
  only `_connection`; three of the module's five grandfathered long functions are queries
  (`src/core/usage_db.py:409`, `:514`, `:632`), two are writer (`_flush_row`, `init_db`).
  Split into a package with `__init__` re-exporting every public name.
- **Re-exports do NOT preserve patch targets — rewrite them in the same commit.** After the
  split, `schedule_flush` resolves `_flush_row` through its own module globals, so
  `patch("src.core.usage_db._flush_row")` would patch only the inert `__init__` alias. The
  six patches at `tests/unit/test_usage_db.py:356-389` (`logger`, `get_connection`,
  `_flush_row`) move to the submodule that the CALLER resolves from.
- **Service preamble is hoisted, not copied.** `src/services/chat_service/chat_service.py:39`
  and `src/services/embedding_service.py:30` open with ~33 identical lines. One
  `BaseService._prepare_dispatch()` returning a small frozen result removes the duplication
  and two func-length violations. Transcription keeps its own shape (no JSON body).
- **`MODEL_CACHE_TTL` is deleted, not implemented.** `src/core/config_manager.py:190` reads
  it and nothing consumes it; the cache is stale-if-error by design, so a TTL would
  contradict `src/core/model_capabilities.py` rather than complete it.
- **Moving code moves its `SYSTEM:` marker and its baseline key.** Steps 3 and 4 relocate
  `# SYSTEM: usage-stats` (`src/core/usage_db.py:12`) and invalidate the description on
  `# SYSTEM: stat-dashboard` (`src/api/stat_page.py:2`, which claims to own the JSON
  endpoints). `pre-commit-gates.sh` blocks on `systems-index --check` drift, and
  `.claude/baselines/func-length.json` is keyed by path, so a moved function is a NEW key,
  not a lowered one. Both are fixed in the same commit as the move, never after.
- **`tests/` joins the ruff gate by ignoring what is correct in a test, not by mass edits.**
  58 findings today; the ignore set below covers 53 and 5 are real bugs to fix. Fixing the
  other 53 is style churn across a suite that is currently the only regression net.

## Risks

- The `AuthContext` change crosses auth → every service → `_validate_and_get_config`; a
  missed call site is a 500 on a live endpoint. Grep the bare names `auth_data`,
  `allowed_models`, `allowed_endpoints` across `src/` AND `tests/` first — the tuple shape
  is baked into `_make_auth_data` in `test_base_service.py` / `test_model_service.py` and
  into `auth_data[0]` at `tests/unit/test_auth.py:34`.
- The `usage_db` split breaks patch targets silently (see Decisions) — an inert patch is a
  green test asserting nothing, not a failure.
- `_prepare_dispatch` sits in the file that owns `identity: passthrough`
  (`src/services/base.py:49-79`). It must not touch those two methods, and it must keep
  computing the identity headers ONCE per request: `chat_service.py:58` feeds the same
  object to the stream and non-stream branches, and `providers/base.py:370` requires both
  paths to send an identical set — a per-branch recompute would hold that by luck.
- Step 1's retry path has no existing test that drives a 429 through a multipart upload —
  it must be written red first, or the fix asserts nothing.

## Order

1. **fix(providers): a retried upload sends the file, not an empty body** — pass `bytes`
   in the files tuple (`openai.py:63`); track drain tasks in a module set
   (`providers/__init__.py:104`). Tests: a 429-then-200 transcription asserting the second
   attempt carries the audio; a rebuild asserting the old pools are closed after the swap.
2. **refactor(auth): AuthContext replaces the positional auth 4-tuple** — new frozen
   dataclass next to `RequestContext`; `get_api_key` returns it; update the four unpack
   sites and the test helpers; drop the unused api_key field. `check_endpoint_access`
   signature is unchanged.
3. **refactor(usage-db): split writer and dashboard queries** — `usage_db/__init__.py`
   re-exporting, `usage_db/writer.py`, `usage_db/queries.py`. Pure move, no SQL edits.
   Rewrite the six patch targets in `test_usage_db.py` in this commit. Keep the
   `SYSTEM: usage-stats` marker on exactly one entry file, regenerate `SYSTEMS.md`
   (`systems-index.py --write`), and re-key the moved func-length baseline entries
   (`func-length-gate.py --update`, justified in the commit body).
4. **refactor(api): stat routes to an APIRouter; hoist the service preamble** — move all
   five `/stat/api/*` handlers (`src/api/main.py:322`, `:327`, `:332`, `:345`, `:358`)
   plus `verify_stat_key` and `_parse_days_param` into `src/api/stat_routes.py`, with one
   `_csv_list()` helper for the three filtered ones; `/stat/` itself stays in `main.py`.
   Add `BaseService._prepare_dispatch` and inline the pass-through `_get_provider`
   (`src/services/base.py:114`). Correct the `SYSTEM: stat-dashboard` description to what
   `stat_page.py` still owns, regenerate `SYSTEMS.md`, and `--update` the baseline for the
   two service functions this shrinks. Leave `_build_identity_headers` /
   `_extract_passthrough_headers` untouched; `tests/unit/test_base_service.py:259-380`
   must pass unedited.
5. **chore: drop dead knobs, untranslated comments, and the tests lint gap** — remove
   `model_cache_ttl` from `_ENV_SETTINGS`, from CLAUDE.md, from `README.md:235`, and delete
   the assert at `tests/unit/test_config_manager.py:294`; translate
   `src/api/main.py:166-167`; add a Cyrillic-in-`src` check to `pre-commit-gates.sh`; add
   `tests/` to the ruff gate with per-file-ignores ASYNC109, ASYNC230, ASYNC240, B007,
   B017, B018, B904, B905, E402, E722, SIM103, SIM105, SIM117, and fix the four real `F841`
   plus the one `F811`. Verify with a clean `ruff check tests` before committing.

## Not doing

- Rebuilding only the changed providers on a config reload. Correct today, just wasteful;
  comes back as its own task if pool churn is ever observed.
- Implementing a real capabilities TTL (see Decisions — it would contradict stale-if-error).
- Collapsing `project_name` to a single owner across `AuthContext` and `RequestContext`.
- Fixing the remaining grandfathered long functions not touched by steps 3 and 4.
- Any change to the SSE passthrough, the header denylist, or the access-check order.

## Validation

Each step ends with `docker compose up -d --build` and a live drive against `:8777`:
non-streaming and streaming (`curl -N`, frames shown verbatim) chat, one allowed key and
one REFUSED key, and `/v1/models`. Step 1 additionally drives a real transcription upload.
Step 2 is the auth surface: both keys are mandatory evidence. Step 3 drives one request and
then reads the new row back out of `/stat/api/requests`, proving writer and queries still
agree across the split. Step 5 is docs/config/lint only — state the exemption and run the
gates. Full `tests/` green before the merge back to `dev`; `pre-commit-gates.sh` UNPIPED
per step.

## Progress

All five steps executed on branch `tech-debt-payoff` (from `dev` @ 430f2c1), each
with its own commit, green gates and a live drive:

1. `fix(providers)` — bytes in the files tuple; drain tasks tracked in
   `_drain_tasks`. Ruling: the EOF-replay premise does not reproduce on pinned
   httpx 0.28.1 (multipart render_data seeks seekable files to 0 — verified with
   a non-seekable wrapper); fix applied anyway as construction-site robustness.
2. `refactor(auth)` — `AuthContext` frozen dataclass; all four unpack sites and
   test helpers rewritten; unused api_key slot dropped.
3. `refactor(usage-db)` — package split (writer/queries/_conn); six patch
   targets rewritten to caller submodules; SYSTEMS.md regenerated; func-length
   baseline re-keyed.
4. `refactor(api)` — stat_routes.py APIRouter + `_csv_list`; stat_page SYSTEM
   description corrected; `BaseService._prepare_dispatch` + `PreparedDispatch`
   (identity headers computed once, INVARIANT pinned); `_get_provider` inlined;
   baseline 17 -> 16 (create_embeddings paid off).
5. `chore` — MODEL_CACHE_TTL deleted everywhere; main.py ARCH comment
   translated; cyrillic-src gate added; tests/ under ruff with the planned
   per-file-ignores (+B008, the FastAPI Depends idiom) and the 5 real bugs
   fixed; `ruff check src/ tests/` clean.

Outstanding before merge: the 11 failing live-upstream API tests
(gemini_mini: OpenRouter delisted google/gemini-2.0-flash-001; deepseek_flash:
reasoning-first model returns empty content at the tests' token budgets) are
environmental — identical set across two repeat runs; every local/orange-backed
test passes and every live drive was green. Merge to `dev` pending review
approval.
