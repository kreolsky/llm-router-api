# Request path: one dispatch funnel, one error extractor, named routes

## Decisions

Everything here is about a contract that exists in prose but not in structure.
The pieces share the request path and the `RequestStats` holder; the capabilities
split rides along as a low-risk tail.

**The dispatch funnel is split so transcription can join it.** `_prepare_dispatch`
(`src/services/base.py:152`) is documented as the single funnel and is where
`apply_reasoning_effort` lives, but it parses the JSON body itself and reads
`model` out of it. Multipart cannot enter that signature, so
`create_transcription` (`src/services/transcription_service.py:26`) is a second
copy of the same preamble: `_validate_and_get_config` (`src/services/base.py:107`),
`get_provider_instance`, `_build_identity_headers` (`src/services/base.py:95`),
stats enrichment. Splitting into a body-agnostic `_resolve_target(model_id, ...)`
plus a thin JSON wrapper makes the funnel true by construction, so the next
cross-cutting policy cannot miss an endpoint the way it would today. The
identity-headers `INVARIANT` (`src/services/base.py:160`) moves onto the resolver
verbatim — it is what makes the shared path load-bearing.

**One extractor owns the error envelope.** `custom_http_exception_handler`
(`src/api/main.py:91`) and `_apply_stream_error`
(`src/services/chat_service/stream_processor.py:273`) independently walk the same
`{"error": {message, metadata: {error_code, provider_name}}}` shape and write the
same three stats fields. Two implementations of one contract drift silently when
the envelope gains a field.

**The endpoint name lives on the route, and the middleware reads it there.**
`_ENDPOINT_NAMES` (`src/api/middleware.py:34`) is a literal copy of the route
table in `src/api/main.py`; a new route lands in the usage rows as a raw path and
no test catches it. The names themselves are NOT derivable: the stored rows use
`chat`/`embeddings`/`models`, while `route.name` would give `chat_completions`,
and those values are already persisted (`src/core/usage_db/writer.py:63`). So the
value stays a literal but moves to the one place that cannot be forgotten — an
explicit `name="chat"` on each route decorator — and the middleware reads
`scope["route"].name`. That read is only possible AFTER `await self.app(...)`
populates the route, so `endpoint` is assigned in the `finally` before the flush
instead of at construction (`src/api/middleware.py:84`). The test then walks
`app.routes` and requires a name on every non-skipped route, which is what makes
the next route fail loudly.

**`StreamProcessor.config_manager` is dead.** It is assigned at
`src/services/chat_service/stream_processor.py:94`, and its only read in `src/`
is the init log line (`src/services/chat_service/stream_processor.py:96`); about
twenty test call sites pass it. Both the field and that log field go.

**The capabilities module splits by concern.** `src/core/model_capabilities.py`
holds normalizers, the store (`:291`) and the refresh orchestration (`:375`) in
one file, and the llama-server native-`models` merge sits inside the refresh loop
(`:420`) instead of inside the llama normalizer — upstream shape knowledge leaked
into the scheduler, which is why that function runs to 80 lines. A package with
`normalizers.py`, `cache.py` and `refresh.py` keeps one `SYSTEM:` marker on the
package `__init__.py`.

## Risks

- Step 1 crosses auth to provider on every endpoint. Regressions show up as a
  changed provider payload, not a failing assertion, so the drives compare the
  upstream-bound body for all three endpoints.
- Transcription joining the funnel must NOT start applying the reasoning-effort
  policy: STT models carry no such block, but the resolver split has to keep that
  step in the JSON wrapper, not in the shared resolver.
- Step 3 moves an assignment inside the ARCH-marked single usage-stats writer
  (`src/api/middleware.py:6`). The flush stays exactly where it is, in `finally`,
  and `endpoint` must be set before it on EVERY exit path — including the
  `except` branch and a client disconnect mid-stream, which are the rows the
  stats exist to record. A route that never resolved (404) keeps the raw path.
- Step 3 must not change a single stored value: `chat`, `embeddings`,
  `transcriptions`, `models`, `generate_key`, and `/v1/models/{id}` still
  recording as `models`. Old rows and new rows have to keep grouping together.
- The capabilities move is a rename-and-move: it needs the internal-symbol
  refactor scan across `src/` and `tests/`, including `patch("...")` string
  targets, before it is called done.

## Order

1. **Split the funnel.** Extract `_resolve_target` from `_prepare_dispatch`;
   `_prepare_dispatch` becomes the JSON wrapper that parses the body and applies
   the effort policy. Move `create_transcription` onto the shared resolver.
2. **One envelope extractor.** Add a single `enrich_stats_from_envelope` in
   `src/core/error_handling/`; both the HTTP handler and the stream processor
   call it. Assert over the shared function, not over duplicated literals.
3. **Name the routes.** Add `name=` to every route in `src/api/main.py` carrying
   its current stored value; drop `_ENDPOINT_NAMES` and `_endpoint_name`; set
   `stats.endpoint` from `scope["route"].name` in the `finally`, falling back to
   the raw path. Keep `_SKIP_PATH_PREFIXES` (`src/api/middleware.py:30`) — a
   policy list, not a copy of the routes. Test walks `app.routes`.
4. **Delete the dead parameter.** Drop `config_manager` from `StreamProcessor`,
   from its init log, from its call site
   (`src/services/chat_service/chat_service.py:21`) and from test fixtures.
5. **Split the capabilities module** into a package; move the llama native-caps
   merge into the llama normalizer, behind `normalize_provider_model`
   (`src/core/model_capabilities.py:264`). Regenerate `SYSTEMS.md`.

## Not doing

- Changing any served response shape or any stored value: `/v1/models`, the error
  envelope and the usage row keep their exact fields AND their exact endpoint
  strings. This epic is structural only.
- Deriving endpoint names from handler function names — it would rewrite what
  historical rows mean.
- Reworking `RequestStats` into an immutable or context-var carrier. The ambient
  mutable holder is worth revisiting, but not while the funnel is moving.
- Touching the reasoning-effort policy or the manual/auto capability precedence.

## Validation

Full `tests/unit/` after each step and the `tests/api/` files each step touches;
a green full suite before the merge. Against the rebuilt container on `:8777`:

- Chat non-streaming, chat streaming (`curl -N`, frames shown), embeddings and a
  real audio transcription — all four after step 1, since all four now share one
  resolver. Provider-bound headers captured for each and compared to the
  pre-change capture.
- An allowed key and a REFUSED key against a restricted model, plus a model
  outside the registry: the stats rows must carry the same `error_code` values as
  before steps 1 and 2.
- A mid-stream upstream failure driven so the SSE error frame and the usage row
  are read together — they come from the one extractor after step 2.
- Step 3: `SELECT DISTINCT endpoint FROM usage_events` before and after, over drives of
  all five endpoints plus a 404 and a client-aborted stream — the set must be
  unchanged and no row may carry a raw path for a route that exists.
- `/v1/models` and `/v1/models/{id}` diffed byte-for-byte across step 5.
- `.claude/scripts/pre-commit-gates.sh` unpiped before each commit; entries that
  step 1 and step 5 resolve are removed from `.claude/baselines/func-length.json`
  in the same commit.

## Progress

Not started.
