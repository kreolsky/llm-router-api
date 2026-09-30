# Chained router keeps the upstream reasoning block

## Decisions

- Topology: external client → ext router (`server-ai-api-ext`, provider `main`) → main router (`http://api.ai.gray/v1`). Ext fills its capabilities auto-cache from main's `/v1/models`, which is rendered in the OpenRouter shape, so ext normalizes it through `_normalize_openrouter` (`src/core/model_capabilities/normalizers.py:60`).
- Current behaviour to change: `_normalize_openrouter` derives only `reasoning: {"supported": True}` from `supported_parameters` (`src/core/model_capabilities/normalizers.py:78`-`src/core/model_capabilities/normalizers.py:86`) and ignores the top-level `reasoning` object main already renders. Observed on prod: main serves `glm/flash` with `reasoning.effort_levels [low, high, max]`, ext serves `glm/flash` with `reasoning: None`; `deepseek/flash` loses `effort_levels [low, high]` and `default_enabled`.
- Fix: when the raw entry carries a `reasoning` dict, `_normalize_openrouter` copies from it exactly the stored keys `supported` (bool), `effort_levels` (list of str), `default_effort` (str), `default_enabled` (bool); a value of the wrong type is dropped, unknown keys are dropped. The result is merged OVER the `supported_parameters`-derived flag, so an explicit `supported: false` upstream is honoured.
- Foreign defaults are dropped at read time: real OpenRouter entries carry a top-level `reasoning` object too, with their own vocabulary (observed: `gemini/mini` cached `default_effort: minimal`, `default_enabled: true`), and a merge replaces `effort_levels` but keeps a foreign `default_effort`. `ModelService._resolve_stored_capabilities` (`src/services/model_service.py:61`) calls a new `_drop_foreign_default_effort` on the cache+policy layer, before `model_info`: a `default_effort` outside `effort_levels` is deleted and a `logger.warning` (`error_type=capabilities_config_conflict`) names the model, the value, the levels and the config fix. Warned once per (model, value, levels) per process, because this path runs on every `/v1/models` request and every usage flush. `model_info.yaml` keeps the last word unchecked.
- Shape detection: a model main serves from a generic upstream (e.g. `glm/flash` via z.ai) renders only `reasoning`, so `_is_openrouter_shape` (`src/core/model_capabilities/normalizers.py:26`) also accepts a top-level `reasoning` dict; without it the entry normalizes to `{}` (observed on ext after deploy).
- Precedence otherwise needs no change: `_resolve_stored_capabilities` merges `cache → derived models.yaml policy → model_info` (`src/services/model_service.py:89`), so an ext-side `reasoning_effort` block still replaces the cached `effort_levels` (lists replace, `merge_capabilities` in `src/core/model_capabilities/render.py`) and `/v1/models` stays equal to what ext's own effort gate enforces. With no ext policy, main's levels are shown and main's gate enforces them — also consistent.
- `/v1/capabilities` on ext reads the same `_resolve_stored_capabilities`, so it inherits the fix with no change (`src/api/main.py:189`).
- Update the `WHY:` at `src/core/model_capabilities/normalizers.py:81` and the `normalize_provider_model` docstring: effort levels ARE derivable when the upstream is itself a router of this kind; still not from `supported_parameters`. Update the `CLAUDE.md` Model Capabilities sentence "`effort_levels`/`default_effort` come from the `models.yaml` policy and `default_enabled` is manual-only — no upstream shape expresses either" accordingly.
- Size: S, one commit to `dev`, low entanglement (one normalizer function plus one read-time guard in `ModelService`, no hot-path file, no request-path boundary).

## Risks

- OpenRouter's `default_enabled` is now stored and advertised for openrouter-backed models. Signal: a harness enabling reasoning where it previously did not.
- Stale ext cache until the next refresh (`MODEL_CACHE_REFRESH_INTERVAL`, 3600s). Mitigated in Validation by the container restart that the deploy performs.

## Order

1. `fix(capabilities): keep the upstream reasoning block when normalizing` — `src/core/model_capabilities/normalizers.py` (`_normalize_openrouter` + `WHY:` + docstring), tests in `tests/unit/test_model_capabilities.py` class `TestNormalizeOpenRouter`, `src/services/model_service.py` (`_drop_foreign_default_effort`), `CLAUDE.md` sentence. Tests (write first, see them fail):
   - an entry with `reasoning: {supported: true, effort_levels: [low, high, max], default_effort: high, default_enabled: true}` normalizes to exactly those four keys;
   - `reasoning` present, `supported_parameters` absent → still stored;
   - `reasoning: {supported: false}` with `reasoning_effort` in `supported_parameters` → `supported: false`;
   - wrong types (`effort_levels: "high"`, `default_enabled: "yes"`) and unknown keys are dropped; a non-dict `reasoning` is ignored;
   - `tests/unit/test_model_service.py` `TestReasoningEffortDerived`: an OpenRouter-shaped cache entry with `default_effort: minimal` under a `[low, high]` policy loses the default, keeps `default_enabled`, and warns exactly once across `retrieve_model` + `list_models`; a chained `[low, high, max]`/`max` cache under a `[low, high]` policy loses the default; a default inside the levels is kept with no warning;
   - round trip: `normalize_provider_model(<a ModelService.list_models entry for a model with a models.yaml reasoning_effort policy>)` keeps `effort_levels` — binds main's renderer to ext's normalizer instead of a literal.

## Not doing

- Opening `/v1/capabilities` for the `xisraa` key on ext: an access-control change on the prod server, left to the operator (`allowed_endpoints` in ext `config/user_keys.yaml`).
- Clearing ext `config/model_info.yaml` — already done on the server; it no longer masks main's vision data.
- Passing through `supports_vision` / `modality`: they are derived by `render_capabilities` from `architecture.input_modalities`, which already survives the hop.

## Validation

- Unit: `pytest tests/unit/test_model_capabilities.py -q` green; `.claude/scripts/pre-commit-gates.sh` green.
- Local drive: `docker compose restart api`; `curl -s localhost:8777/v1/models -H "Authorization: Bearer <debug key from config/user_keys.yaml>"` unchanged for main-direct models.
- Prod, after `deploy-server` to BOTH `server-ai-api` and `server-ai-api-ext` (ext runs the same code): the deploy restart re-runs the ext refresh immediately (the xisraa key has no grant for `/v1/models/{model_id:path}`, `src/api/main.py:199`, so `?refresh=true` is not used); on the docker host `curl -s localhost:8778/v1/models -H "Authorization: Bearer <xisraa>"` → `glm/flash` has `reasoning.effort_levels == [low, high, max]`, `deepseek/flash` has `effort_levels [low, high]`, `default_enabled: true`, `supports_vision: true`; `glm/pro` keeps `default_effort: high` from the ext policy.
