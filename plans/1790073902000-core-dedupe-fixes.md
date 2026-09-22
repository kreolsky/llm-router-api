# Core dedupe: one persist per refresh cycle, one missing-sections rule

Follows `api-surface-minimization`; independent of it in code, sequenced to keep
one epic in flight.

## Decisions

### C. `cache.persist()` once per refresh cycle, not once per provider

- `src/core/model_capabilities/refresh.py:86` `refresh_provider_capabilities` gains a
  keyword `persist: bool = True`; the try/except `cache.persist()` at lines 127-130
  runs only when True.
- `src/core/model_capabilities/refresh.py:133-144` `refresh_all_capabilities`: call
  each provider with `persist=False`, then persist ONCE after the loop in its own
  try/except with the same warning text (`"Capabilities cache persist failed: {e}"`).
- The direct caller `src/services/model_service.py:204` (`?refresh=true` debug path)
  keeps the default `persist=True` — a single-provider debug refresh still reaches disk.
- Test in `tests/unit/test_model_capabilities.py`, inside
  `TestRefreshProviderCapabilities` (line 355) using `_FakeProvider`/`_FakeCM`
  (lines 333/341): `test_refresh_all_persists_once` — `tmp_path` cache, two providers
  in the fake config, run `refresh_all_capabilities`, assert the cache file was
  written exactly once (a `CapabilitiesCache` subclass counting `persist()` calls —
  the public method, not a patched seam). Second test:
  `test_refresh_provider_default_persists` — a lone `refresh_provider_capabilities`
  call still writes the file.

### E. One missing-sections helper for startup assert and reload reject

- `src/core/config_manager.py`: add `@staticmethod _missing_sections(config) ->
  list[str]` returning the empty-or-absent names among
  `("providers", "models", "user_keys")`.
- `src/core/config_manager.py:243` `_assert_config_complete` (staticmethod, name kept —
  pinned by `tests/unit/test_config_manager.py:393-413`): raises `RuntimeError`
  naming ALL missing sections in one message that keeps the substring
  `"missing or empty"` and each section name (tests match `"missing or empty"` and
  `"user_keys"`). Message shape:
  `Configuration section(s) 'a', 'b' missing or empty. Refusing to start.`
- `src/core/config_manager.py:314`: `if new_config.get('providers') and ...` becomes
  `if not self._missing_sections(new_config):`. The reject warning at line 369 keeps
  its text.
- Test: `test_reload_rejects_partial_config_names_sections` is NOT added — the reject
  path is already covered; add only `test_missing_sections_lists_all` beside
  `TestAssertConfigComplete`: `{"providers": {}}` → `["providers", "models", "user_keys"]`.

## Risks

- C: if `refresh_all_capabilities` is interrupted between the last upsert and the
  single persist, that cycle's fetches are lost from disk (earlier providers' results
  used to be on disk already). In-memory cache unaffected; the next cycle re-persists.
- E: the assert message now lists every missing section instead of the first; any
  operator grepping logs for the old single-section phrasing sees the new shape.

## Order

Branch `core-dedupe-fixes` from `dev`, after `api-surface-minimization` is merged.

1. **C**: `persist` keyword, once-per-cycle persist, two tests.
   `python -m pytest tests/unit/test_model_capabilities.py --tb=short`.
   Commit: `refactor(capabilities): persist the cache once per refresh cycle`.
2. **E**: extract `_missing_sections`, reuse at both sites, one test.
   `python -m pytest tests/unit/test_config_manager.py tests/unit/test_startup_validation.py --tb=short`.
   Commit: `refactor(config): single missing-sections rule for assert and reload`.
3. Full suite `python -m pytest tests/ --tb=short`, `.claude/scripts/pre-commit-gates.sh`
   unpiped. Pre-merge audit `git diff dev core-dedupe-fixes --stat`, merge into `dev`,
   delete the branch.

## Not doing

- Moving `reasoning_effort`/`reasoning_dialect` into `core/`; `/v1/models` render
  cache; SQLite write batching; merging the `get_summary` scans — see the
  `api-surface-minimization` plan's Not doing.
- Making `persist()` atomic (write-then-rename) — a different fix for a different risk.

## Validation

- Cycle (C): scratch container with `MODEL_CACHE_REFRESH_INTERVAL=5`, two providers
  in `models.yaml`; `stat -f %m data/model_cache.json` across two cycles shows one
  mtime change per cycle. `curl :8777/v1/models/<id>?refresh=true` still bumps the mtime.
- Reload (E): live container; empty `models:` in `config/models.yaml` → within 5s the
  log shows "Partial config reload rejected, keeping previous config" and
  `curl :8777/v1/models` still lists the models; restore the file → reload applies.
  Startup with an empty section refuses to start with the new message (capture verbatim).
- Non-streaming + streaming smoke request after the merge.
