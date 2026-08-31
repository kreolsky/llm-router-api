# Provider layer: typed settings, inline retry, extracted pool, ordered reload

Size L (four commits in `## Order`) — branch from `dev`.

## Decisions

The provider layer carries four separable jobs in one class and one duplicated
copy of the config defaults. They are done in one epic because they share a
single file and a single test module; splitting them means re-testing the pool
lifecycle three times.

**Typed `Settings` replaces the duck-typed `config_manager`.** `_TIMEOUT_DEFAULTS`
(`src/providers/base.py:26`) and `_RETRY_DEFAULTS` (`src/providers/base.py:33`)
are a second copy of the defaults declared in `ConfigManager._ENV_SETTINGS`
(`src/core/config_manager.py:201`), held in sync by a drift test
(`tests/unit/test_base_provider.py:331`). A frozen `Settings` dataclass, built
once by `ConfigManager` and passed to the provider as a required argument,
deletes both maps, the drift test, `_get_timeout` (`src/providers/base.py:405`,
read at `:255` and `:585`), the `__getattr__` indirection
(`src/core/config_manager.py:240`) and every `if self.config_manager is not None`
branch (`src/providers/base.py:219`, `:294`, `:412`).

**`Settings` replaces `config_manager` along the whole provider chain, not just
in the constructor.** `config_manager: Any | None` is threaded through
`_build_provider` (`src/providers/__init__.py:34`), `get_provider_instance`
(`:52`) and `rebuild_provider_cache` (`:81`), and supplied by three callers:
`src/services/base.py:190`, `src/services/transcription_service.py:81`,
`src/core/model_capabilities.py:405`. All three already hold the manager, so the
parameter becomes a required `settings: Settings` and each caller passes
`config_manager.settings`. That removes the `| None` duck typing from the chain
instead of relocating it into the factory.

**Order matters: settings before extraction.** Extracting the pool component
first would shape it around `config_manager | None` and force an immediate
rewrite one commit later.

**Retry is inlined before the pool is extracted.** `retry_on_rate_limit`
(`src/providers/base.py:55`) reaches into `args[0].config_manager` by `hasattr`
to configure itself. It decorates one method of one class, and that reach-in is
exactly what makes the surrounding code awkward to lift. An explicit loop inside
`_make_request_inner` reads shorter and takes its values as arguments.

**The pool becomes a component, not a base-class role.** `_build_client`
(`:208`), `aclose` (`:235`), `_acquire_slot` (`:268`) and the
`_inflight`/`_idle`/`_closed` accounting form one coherent object with three of
the project's load-bearing invariants. Today they can only be exercised through a
whole provider. Composition makes the drain and the semaphore directly testable;
the `INVARIANT:` markers move with the code.

**Reload publishes in two phases, via an explicit post-swap callback list.**
`reload_config` runs callbacks at `src/core/config_manager.py:282`, then swaps
`self.config` at `:292`. In that window `get_config()` still returns the old
config, so a request resolving a provider removed by the new config hands its
stale `provider_config` to `get_provider_instance` and re-populates the freshly
rebuilt cache. Fixing this needs a phase `reload_config` does not have, so
`ConfigManager` gains `add_post_swap_callback(cb, name=...)` beside
`add_reload_callback` (`:254`): pre-swap callbacks keep their abort-the-reload
contract, post-swap ones run after `self.config = new_config` and can only log on
failure — the config is already published and there is nothing to roll back to.
`rebuild_provider_cache` splits accordingly: `prepare_provider_cache` builds and
stages the new instances (keeping the collect-all-errors fail-fast), and
`publish_provider_cache` swaps the module cache in and drains the superseded
pools. Startup (`src/api/main.py:37`) calls both back to back.

## Risks

- The pool extraction touches the SSE drain path. A mistake surfaces as a config
  reload cutting a live stream, which no unit test reproduces on its own — hence
  the live reload-under-stream drive in Validation.
- Removing the drift test looks like "changing a test to make code pass". It is
  not: the test pinned two copies of the defaults to each other and one copy is
  gone. The commit body must say so explicitly.
- `config_manager=None` is load-bearing in `tests/unit/test_base_provider.py`
  fixtures (`:47`, `:88`, `:308-326`, `:545`, `:772`). Those fixtures are
  rewritten to pass `Settings()`, not deleted. The `get_provider_instance` patch
  targets in `tests/unit/test_base_service.py:234` and
  `tests/unit/test_transcription_service.py:60` see the new signature.
- Step 4 changes reload semantics, which is decision-pinned behaviour: it owes an
  `INVARIANT:` + `Why:` on the new publish order, and the atomicity contract in
  the `reload_config` / `add_reload_callback` docstrings
  (`src/core/config_manager.py:256-259`, `:265-267`) is rewritten to name both
  phases.

## Order

1. **Typed settings.** Add a frozen `Settings` dataclass; `ConfigManager` builds
   one at construction and exposes it as `.settings`. Provider takes `settings`
   as a required argument, and so do `_build_provider`,
   `get_provider_instance` and `rebuild_provider_cache`; the three callers pass
   `config_manager.settings`. Delete `_TIMEOUT_DEFAULTS`, `_RETRY_DEFAULTS`,
   `_get_timeout`, `ConfigManager.__getattr__` and the `TestEnvDefaultsDrift`
   class; rewrite the provider fixtures.
2. **Inline the retry.** Replace `retry_on_rate_limit` with an explicit backoff
   loop in `_make_request_inner`, taking its bounds from `settings`. Add a `WHY:`
   on `_stream_request_inner` recording that streaming carries no retry because
   `open_provider_stream` already surfaces the upstream status.
3. **Extract the pool.** Move client construction, `aclose`, `_acquire_slot` and
   the in-flight accounting into a component the provider composes. The three
   existing `INVARIANT:` markers move verbatim with their code.
4. **Two-phase reload.** Add `add_post_swap_callback`; split
   `rebuild_provider_cache` into `prepare_provider_cache` /
   `publish_provider_cache`; register prepare pre-swap and publish post-swap in
   `src/api/main.py:49-53`, and call both from `_validate_providers`. Pin the
   order with an `INVARIANT:` + `Why:`.

## Not doing

- Collapsing `BaseProvider` / `OpenAICompatibleProvider` into one class. The
  single-subclass seam is real indirection, but removing it is a separate task
  and would collide with every step here.
- `StreamProcessor(config_manager=None)`
  (`src/services/chat_service/stream_processor.py:93`) is the same duck-typing,
  and it belongs to the request-path plan — it keeps its current signature here.
- Adding a second provider type, a provider protocol, or any injection point.
- Touching `_merge_request_headers` (`src/providers/base.py:416`) or the header
  policy: passthrough identity is out of scope for this epic.

## Validation

Full `tests/` after each step, plus a repeat run after steps 3 and 4 (pool
lifecycle and reload ordering are race-shaped). Then, against the rebuilt
container on `:8777`:

- One non-streaming and one streaming chat request (`curl -N`), frames captured
  verbatim.
- A `max_concurrent` provider driven past its limit: one request served, one
  refused with the queue-timeout 503, and the 503 distinguishable in the stats
  row from the pool-closing 503.
- A live `curl -N` stream running while `config/models.yaml` is touched to force
  a real hot reload: the stream must finish intact, and the reload must be
  visible in the log. Repeat with a provider REMOVED from `providers.yaml` to
  drive step 4's window.
- `.claude/scripts/pre-commit-gates.sh` unpiped before each commit; resolved
  entries removed from `.claude/baselines/func-length.json` in the same commit.

## Progress

- Step 1 (typed settings) DONE: frozen `Settings` in `src/core/config_manager.py`
  (field defaults are the single copy of the no-config fallbacks; env var =
  upper-cased field name), `ConfigManager.settings` replaces `__getattr__`,
  provider chain takes a required `settings`. `_TIMEOUT_DEFAULTS`,
  `_RETRY_DEFAULTS`, `_get_timeout`, `TestEnvDefaultsDrift` deleted; fixtures
  rewritten to `Settings(...)`. Full suite green (631 passed, 1 skipped),
  ruff clean. Ruling logged: env-name convention derived from field names
  (every legacy var already matched), so no second defaults map exists and
  the drift test has nothing left to pin.
- Step 2 (inline retry) DONE: `retry_on_rate_limit` deleted; explicit backoff
  loop in `_make_request_inner` over a new `_make_request_attempt`; bounds
  from settings; `WHY:` added on `_stream_request_inner` (streaming carries
  no retry — open_provider_stream already surfaces upstream status).
  Decorator tests ported to drive through `_make_request`. Full suite green
  (632 passed, 1 skipped), ruff clean.
- Step 3 (extracted pool) DONE: `src/providers/pool.py` `ProviderPool`
  (client construction, semaphore, in-flight accounting, aclose drain) —
  the ARCH/INVARIANT blocks moved verbatim; BaseProvider composes
  `self.pool` and delegates aclose; no `client` alias (grep-clean rename).
  Pool-shaped tests moved to tests/unit/test_provider_pool.py driving the
  component directly. Full suite run 3x: one flake in an unrelated
  /v1/models caching API test on the cold first run, then 640 passed twice.
  SYSTEMS.md regenerated (also fixed a pre-existing usage-stats line drift).
