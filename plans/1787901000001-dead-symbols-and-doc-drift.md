# Remove dead provider symbols and fix doc/env drift

## Decisions

L, branch from `dev`. Runs AFTER
`plans/1787901000000-remove-message-sanitization.md`, which deletes ~200 lines
from `stream_processor.py` above `_format_error` and rewrites `tests/README.md`.
Line numbers here predate that: locate each target by symbol, never by line.

Two dead symbols, confirmed by a full grep over `src/`, `tests/`, `scripts/`
and the docs:

- `get_model()` — `src/providers/base.py:589` and its override
  `src/providers/openai.py:100`. Nothing in `src/` calls it; `retrieve_model`
  reads from the capabilities store (`src/services/model_service.py:163`) and
  never touches the network. Only `tests/unit/test_base_provider.py:536-559`
  keeps it alive. `list_models()` STAYS — it is the live source for the
  capabilities refresh (`src/core/model_capabilities.py:393`) and was
  `get_model`'s dependency, not the other way round. README's Project Structure
  never names `get_model`, so no doc edit follows from this deletion.
- `StreamProcessor._format_error` — `src/services/chat_service/stream_processor.py:232`.
  A one-line wrapper over `_frame_error(_error_payload(...))`; the live path
  calls those two directly at `:173-175`.

**`TestFormatError` is retargeted, not deleted.** It is the only test asserting
the error FRAME a client receives — `error.code`, the string-vs-dict
`HTTPException.detail` extraction, the trailing `data: [DONE]`
(`tests/unit/test_stream_processor.py:203-239`). `TestStatsEnrichment` drives the
same failure but asserts only `stats.*`. So each case moves to `process_stream`
with a raising generator, reusing the existing `_parse_error_frame` helper. That
also fixes a testing-rule violation: the class currently tests a private wrapper
instead of the interface.

`USAGE_DB_PATH` is read at import via a bare `os.environ.get`
(`src/core/usage_db.py:24`) — the one env setting outside `ConfigManager`, and
absent from the CLAUDE.md env list. The constant is DELETED (two sources of
truth otherwise): the value moves to `_read_env_settings` as `usage_db_path`
next to `model_cache_path` (`src/core/config_manager.py:200` — string settings
live there, the `_ENV_SETTINGS` tuple is numeric-only) and reaches
`init_db(db_path: str)` from the lifespan (`src/api/main.py:75`, where
`config_manager` is in scope). `import os` stays in `usage_db.py` —
`os.makedirs` / `os.path.dirname` still use it.

"HMAC authentication" (`src/core/auth.py:2`, `CLAUDE.md:19`, `SYSTEMS.md:12`,
`README.md:163`) is wrong: there is no HMAC scheme, only `hmac.compare_digest`
for constant-time comparison (`src/core/auth.py:62`). Wording is corrected, code
is not.

## Risks

- `get_model` is a public method on `BaseProvider`. Before deleting, repeat the
  bare-name grep over `tests/` for `patch("...get_model")` string targets.
  `tests/api/test_models_endpoints.py:234` is a same-named local HTTP helper and
  must NOT be touched.
- `init_db()` gains a required argument. Call sites: `src/api/main.py:75` and
  four in `tests/unit/test_usage_db.py` (`:37`, `:111`, `:130`, `:155`) plus the
  `db_path` fixture at `:29-33`, whose `monkeypatch.setattr(usage_db, "DB_PATH",
  path)` must become a plain returned path passed as the argument.
- The static-mount change is cosmetic: Docker's WORKDIR is `/app`, so
  `directory="src/static"` resolves correctly today. It is consistency work, and
  if the drive in Validation shows any 404 it is reverted, not debugged.

## Order

1. Delete `get_model` from `base.py` and `openai.py` and drop
   `tests/unit/test_base_provider.py:536-559`. Delete `_format_error` from
   `stream_processor.py` and retarget every `TestFormatError` case onto
   `process_stream` with a generator that raises the same exception, asserting
   the parsed frame exactly as today; drop the `_format_error` mention from the
   `test_stream_processor.py` row of `tests/README.md`.
2. Move `USAGE_DB_PATH` into `ConfigManager._read_env_settings` as
   `usage_db_path`, delete the `DB_PATH` constant, give `init_db` a `db_path`
   parameter and pass `config_manager.usage_db_path` at `src/api/main.py:75`.
   Rewrite the `db_path` fixture and the four `init_db()` calls. Add a
   `usage_db_path` case to `tests/unit/test_config_manager.py` mirroring the
   `model_cache_path` pair at `:295-299` (default plus env override). Document
   the var in the **Stats** bullet of the CLAUDE.md env list (`CLAUDE.md:57`),
   NOT the capabilities-cache one.
3. Docs and conventions. Correct the HMAC wording at `src/core/auth.py:2`,
   `CLAUDE.md:19` and `README.md:163`, then regenerate `SYSTEMS.md`
   (`python3 .claude/scripts/systems-index.py --write`) — `pre-commit-gates.sh`
   blocks on drift. Rename `_STATIC_DIR` to `STATIC_DIR` in
   `src/api/stat_page.py:9` and import it for the mount at `src/api/main.py:96`,
   replacing the cwd-relative `"src/static"`. Add the posture note to
   `.claude/rules/workflow.md` (after `## Hard rules`, `:186`) — this edit is
   gated, so produce the block below in your OWN session first:

   - Observation: run `grep -c STAT_API_KEY .env` (expect `0`, exit 1) and
     `grep -n allowed_endpoints config/user_keys.yaml` (the `debug` key's list
     is empty = unrestricted). Paste both verbatim.
   - Rule, in the user's words: this router runs inside a home network;
     security-for-security's-sake is not attempted. An unset `STAT_API_KEY` and
     an unrestricted `/tools/generate_key` are a deliberate posture, so `/review`
     and audits must not raise them as findings.
   - File: `.claude/rules/workflow.md`.

## Not doing

- Removing `OPENAI_API_KEY` from `.env` or its example at `README.md:152`. No
  `api_key_env` in `config/providers.yaml` references it, but the ability to add
  an `openai` provider is unaffected either way — that is a plain `type: openai`
  entry pointing `api_key_env` at whatever name is set.
- Setting a `STAT_API_KEY` or restricting `/tools/generate_key` — ruled out above.
- Touching `list_models`, `_capture_usage_from_chunk`, `_remap_reasoning_in_chunk`.

## Validation

Steps 1 and 3 have no runtime surface of their own: full `tests/unit/` plus
`.claude/scripts/pre-commit-gates.sh` run UNPIPED is their acceptance. Step 2
touches startup and the usage write, so after `docker compose up -d --build`,
captured verbatim:

1. `docker compose logs api --tail 30` — startup clean, no traceback.
2. A chat request through `:8777`, then
   `sqlite3 data/usage.db 'select id,model_id,endpoint from usage_events order by id desc limit 1'`
   — the row landed, proving `init_db(db_path)` opened the mounted file and not
   a fresh one elsewhere.
3. `curl -s -o /dev/null -w '%{http_code}\n' localhost:8777/stat/static/stat.js`
   and `.../stat/` — both 200 after the mount change.
4. Auth admits and REFUSES: the same request with `Bearer dummy` (200) and with
   `Bearer nope` (401), showing the HMAC-wording edit touched no logic.
