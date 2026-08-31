# Config reload: stop rebuilding unchanged provider pools

## Decisions

**Reuse, don't rebuild.** `prepare_provider_cache` builds every configured provider on
every reload (`src/providers/__init__.py:87`), and it is registered as a pre-swap callback
for all four watched files (`src/api/main.py:69`), so a `models.yaml` edit tears down all
seven httpx pools. Fix: carry an unchanged provider's *instance* into the staged cache
instead of constructing a new one. Sameness is `provider_config == live_config[name]`
(plain dict equality on the YAML-loaded mapping) AND the same `Settings` object — settings
are frozen at construction and never change without a restart, so identity is enough.

**Why instance reuse and not pool reuse.** The provider owns its `ProviderPool`, which owns
the semaphore. Rebuilding the provider resets the semaphore, which is what lets the old
pool's in-flight requests and the new pool's fresh slots exceed `max_concurrent` together
during the drain window (up to `stream_read_timeout`). Only carrying the *whole instance*
keeps one semaphore per backend across a reload.

**The reused instance must not be drained.** `publish_provider_cache` closes every value of
the old cache. A reused instance is in both dicts, so it would be closed under itself —
`ProviderPool.aclose` sets `_closed = True` (`src/providers/pool.py:110`) and from then on
`acquire_slot` refuses every request with a 503 (`src/providers/pool.py:147`), permanently.
Publish must therefore drain `old - published` by identity, not the whole old dict.

**A failed publish stops the mtime commit.** `reload_config` returns True even when a
post-swap callback raised (`src/core/config_manager.py:340`), and `_poll_once` commits
`last_mtimes` on True (`src/core/config_manager.py:391`) — so a provider added by that
reload would 404 until the file is touched again. Post-swap failure returns False: the
config stays published (nothing to roll back to), but the on-disk state is not marked
consumed, so the next poll retries.

**The nits ride the last commit** because none of them is worth a branch of its own:
`src/core/auth.py:68` points at `verify_stat_key` in `api/main.py`, which lives in
`src/api/stat_routes.py:23`; `src/core/model_capabilities/normalizers.py:15` imports the
private `_PRICING_KEYS` across a module boundary from `src/core/model_capabilities/render.py:11`;
`src/core/usage_db/writer.py:117` assigns `_conn._connection` directly while every reader
goes through `get_connection()`.

## Risks

* **Reuse must not resurrect a provider the operator deleted.** Sameness is keyed on the
  name being present in the NEW config; a name absent there is never carried over.
* **Dict equality on YAML values.** `_validate_models` mutates `models`, not `providers`,
  so a providers entry is untouched between load and compare. An operator edit that
  reformats YAML without changing values correctly counts as "unchanged".
* **Double-close.** Guarded by identity-based drain plus the existing idempotent `aclose`.
* **Post-swap returning False changes `_poll_once`'s meaning of the return value.** It
  already distinguishes "applied" from "rejected"; this only moves one case across.

## Order

1. **Reuse unchanged provider instances in `prepare_provider_cache`.** Stage keeps the live
   instance when the name exists in both configs with an equal config dict; new and changed
   names are built. Publish drains only instances absent from the published cache (identity
   comparison). `clear_provider_cache_async` dedupes by identity for the same reason. Add
   the `INVARIANT:` + `Why:` on the reuse branch and on the identity-based drain.
2. **Return False from `reload_config` when a post-swap callback fails**, so `_poll_once`
   leaves `last_mtimes` uncommitted and retries on the next tick. Tighten the docstring
   contract on both `reload_config` and `_poll_once`.
3. **Documentation and boundary nits**: fix the `auth.py` cross-reference to
   `stat_routes.py`; promote `_PRICING_KEYS` to a public name in `render.py` and update both
   readers; add a `set_connection()` setter in `_conn.py` that closes any prior connection,
   and call it from `init_db`/`close_db`.

## Not doing

* Per-provider hot-swap of `max_concurrent` without a pool rebuild. Changing the semaphore
  bound on a live pool is a separate contract; a changed provider entry still gets a fresh
  instance, which is today's documented behaviour.
* Watching `providers.yaml` separately from the other three files. The reuse check makes the
  file-level distinction unnecessary and a second watcher is a new failure mode.
* Touching the 18 grandfathered long functions in `.claude/baselines/func-length.json`.

## Validation

Unit: reuse (same config ⇒ `is` the same instance, and it is NOT closed after publish),
replacement (changed config ⇒ new instance, old one closed), removal (name dropped ⇒ closed
and a lookup 404s), addition, and a post-swap failure leaving `last_mtimes` uncommitted so
the next `_poll_once` retries. Full `tests/` plus a repeat run — the diff sits on the pool
lifecycle.

Live drive against `:8777` across a real hot reload:

* `touch config/models.yaml`, wait the interval, confirm the logs show `Configuration
  reloaded` with NO `Provider '<name>' ... concurrency limit` lines (the reuse path is
  silent; today all seven print).
* Edit a real key in `config/providers.yaml`, wait, confirm only that provider reprints.
* Start a streaming request with `-N`, `touch config/models.yaml` mid-stream, and show the
  frames continuing to `[DONE]` — the reused pool must not be drained under a live stream.
* One non-streaming request and one refused key after the reload, to prove the reused
  instance still serves and still gates.

## Progress

- [x] Step 1 — instance reuse in `prepare_provider_cache`; identity-based
      drain in `publish_provider_cache`; identity dedupe in
      `clear_provider_cache_async`; `provider_config` recorded on
      `BaseProvider`. Unit tests green.
- [x] Step 2 — `reload_config` returns False on post-swap failure; docstrings
      tightened on `reload_config`/`_poll_once`.
- [x] Step 3 — auth.py cross-reference fixed; `PRICING_KEYS` public;
      `set_connection()` added and used by `init_db`/`close_db`.
- [x] Validation — full `tests/` green (682-684 passed; one flake in run 1:
      real-upstream streaming + startup timing, both pass isolated and in
      the repeat run). Live drives on :8777 all passed: silent reuse reload,
      single-provider rebuild on a real key edit, stream across a proven
      mid-stream reload to `[DONE]`, non-stream + refused key (403
      model_not_allowed), broken-provider veto retried by the poll while
      serving.
- [x] Phase 4 review — approved. Re-verified against the diff: identity-based
      drain is the only safe direction given pool.py's `_closed` gate;
      `_stale_stage_values` always under `_cache_lock`; `id()` comparisons
      safe (all compared objects strongly held). 552 unit tests green,
      all six pre-commit gates green. One non-blocking residual deferred:
      a `set_connection` whose prior `close()` raises orphans the fresh
      handle (exceptional-only; strictly better than the old always-orphan).
- [x] Phase 5 — committed on `config-reload-pool-churn` in 3 commits:
      provider instance reuse; post-swap-failure retry; boundary nits
      (this commit). Plan complete.
- [x] Phase 4 follow-up — the three review findings fixed: the reload_complete
      line is a WARNING carrying `post_swap_failed` when a post-swap callback
      raised (never the plain success line, which the retry loop would reprint
      every interval); the retry cadence is named in the WHY; `set_connection`
      suppresses a raising close so the swap still installs the fresh handle.
      Both new tests proven red first. 555 unit tests green, all six gates
      green, live drive on :8777 across three reloads with zero pool rebuilds
      and a stream surviving a mid-stream reload to `[DONE]`.
