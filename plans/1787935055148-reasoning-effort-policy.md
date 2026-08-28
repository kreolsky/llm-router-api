# Per-model reasoning effort policy

Sizing: M — one commit, medium entanglement (request path + the /v1/models contract).
Straight to the working branch, no feature branch; Phase 4 review is owed.
Citations below are line numbers on branch `debt-payoff-round-2`; re-grep the symbol if
the plan is executed on a tree where they have moved.

## Decisions

**Single home is `config/models.yaml`.** The effort list is routing behaviour (it decides
what leaves for the upstream), not a curated fact about the model, so it sits next to the
existing `options:` block that already shapes the outgoing body (`config/models.yaml:20`,
merged at `src/providers/base.py:371`). New optional key:

```yaml
local/reasoner:
  reasoning_effort:
    allowed: [low, medium, high]   # values permitted to reach the upstream
    default: high                  # injected when the client sends none
    param: reasoning_effort        # optional wire location: reasoning_effort | reasoning.effort
```

Absent key ⇒ today's behaviour verbatim: the field is passed through untouched.

**`options:` still wins.** It is merged after, in `_apply_model_config`
(`src/providers/base.py:364-371`), and it is the existing escape hatch for a hard-pinned
value (that is what `local/chat`'s `chat_template_kwargs` is). Unchanged — but a model
carrying BOTH `options.reasoning_effort` and `reasoning_effort:` would serve a
`/v1/models` list the upstream never sees, so that combination is a load-time warning
(see the validation decision).

**Enforcement in the one funnel.** New `src/services/reasoning_effort.py` exposing
`apply_reasoning_effort(request_body, model_config, **error_ctx) -> dict`, called from
`BaseService._prepare_dispatch` right after `model_config` is resolved
(`src/services/base.py:182`), so chat and every future body-carrying endpoint get it by
construction rather than per-service. It reads the client value from BOTH `reasoning_effort`
and `reasoning.effort` (a harness picks its own dialect) and writes the default ONLY when
neither is present, at the location `param` names — never both, never over a client value.
That injection line carries a `WHY:`: the body is not passthrough (`identity: passthrough`
is headers only, `src/core/header_policy.py:3`), and injecting a default does shade the
harness fingerprint the upstream sees — accepted because it is opt-in per model and the
`model` field plus `options:` already rewrite the body on the same line.

**A value outside `allowed` is a 400, not a clamp.** Fail-fast: silently downgrading a
harness's `max` to `high` produces an unexplainable bill and no signal. New
`ErrorType.INVALID_PARAMETER_VALUE` (400) beside `MISSING_REQUIRED_FIELD`
(`src/core/error_handling/error_types.py:18`), message naming the allowed list.

**Declared in `/v1/models` from the same key — never re-typed.** `reasoning` gains
`effort_levels: [...]` and `default_effort: <str>` in the stored shape, derived in
`ModelService._resolve_stored_capabilities` (`src/services/model_service.py:60`) so
`list_models` and `retrieve_model` cannot diverge. Layering:
`merge_capabilities(merge_capabilities(cache, derived), model_info)` — derived beats the
auto-cache, `model_info.yaml` still beats everything, so the INVARIANT at
`src/services/model_service.py:63` holds unchanged. The key's presence implies
`reasoning.supported: true` unless `model_info` overrides it.

**Config validation is soft**, in a new `_validate_models(config)` next to
`_validate_model_info` and called from the same place (`src/core/config_manager.py:103`,
sibling at `:117`). Warn and ignore the whole block for that model when: `allowed` is not a
non-empty list of strings, `default` is set but not in `allowed`, `param` is outside
{`reasoning_effort`, `reasoning.effort`}, or `options.reasoning_effort` is also present.
Why soft: models.yaml is hot-reloaded every 5s; a hard raise there kills a running router
on a typo.

## Risks

- Not every upstream reads `reasoning_effort` (OpenRouter wants `reasoning: {effort}`).
  Mitigated by `param:`; a wrong choice is a per-model config fix, no code change.
- Injecting a default where none was sent changes billing for a model that previously ran
  in the upstream's own default mode. The key is opt-in per model, so nothing moves until
  an operator adds it.
- `_prepare_dispatch` is shared with embeddings/transcription; a stray `reasoning_effort:`
  on such a model would inject a field into a body that has no use for it. Accepted —
  operator error, and the load-time warning shows the block that was accepted.

## Order

1. Single commit: `ErrorType.INVALID_PARAMETER_VALUE`; `src/services/reasoning_effort.py`;
   the `_prepare_dispatch` call site; the derived layer in `_resolve_stored_capabilities`;
   `_validate_models` in `ConfigManager`; the `reasoning_effort:` block on `local/reasoner`
   in `config/models.yaml`; docs (the `Model Capabilities` and env/config sections of
   `CLAUDE.md`, the schema header of `config/model_info.yaml:1-40`); the tests below.

## Not doing

- No global default-effort env var — a policy without a model is unroutable.
- No translation of upstream `supported_parameters: [reasoning]` into `effort_levels`; the
  upstream shape cannot express a level list (`src/core/model_capabilities.py:261`).
- No per-key (user_keys.yaml) effort ceiling.
- No normalization between the two client dialects on the way OUT — whatever the client
  sent stays where it sent it; only the injected default has a chosen location.

## Validation

Tests — new `tests/unit/test_reasoning_effort.py`, plus cases in `tests/unit/test_model_service.py`:
- client omits effort ⇒ default injected at `param`'s location, and only there;
- client sends an allowed value in either dialect ⇒ body unchanged, no second field added;
- **client sends a value outside `allowed` ⇒ 400** (the refused principal, per `testing.md`);
- model without the key ⇒ body identical to the input;
- `default` not in `allowed`, and `options.reasoning_effort` present ⇒ warning, block
  ignored, passthrough;
- `/v1/models` and `/v1/models/{id}` both carry `effort_levels`/`default_effort`, asserted
  against the value read from the loaded models.yaml, not a literal;
- `model_info.reasoning` still overrides the derived block.

Live drive against the running container on `:8777` (rebuild first — the image copies
source at build time), evidence captured verbatim:
1. chat completion on `local/reasoner` with no effort ⇒ the outgoing-body debug log shows
   the injected value;
2. same with `"reasoning_effort": "max"` ⇒ 400 envelope naming the allowed list;
3. same with an allowed value and `curl -N` ⇒ frames flow, value untouched;
4. edit `allowed` in `config/models.yaml`, wait out the 5s reload, repeat (2) ⇒ the new
   list appears in the error message with no restart.
