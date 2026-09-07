"""Per-provider reasoning-field dialect translation on the dispatch funnel.

ARCH: the translation lives beside the effort policy in the ONE funnel
(BaseService._prepare_dispatch), keyed on the PROVIDER entry (providers.yaml)
— the family a model is routed to is a property of the deploy, not of the
model id, so the repo and the VM can route the same model differently. The
harness (dsh) emits the DeepSeek wire shape — ``thinking: {type}`` on every
turn, ``reasoning_effort`` beside it when a level is resolved — whatever the
upstream; the router re-shapes those two fields per dialect:

    reasoning_dialect: openai | deepseek | openrouter   (providers.yaml; default openai)

  openai (default): ``thinking`` is dropped — the dialect has no such field —
      and ``reasoning_effort`` passes through untouched.
  deepseek: both fields pass through untouched — the native dialect.
  openrouter: the effort re-nests to ``reasoning.effort`` (vocabulary mapped:
      ``max`` -> ``high``, OpenRouter's ceiling; unknown spellings verbatim),
      a disabled thinking becomes ``reasoning: {enabled: false}``, and an
      enabled thinking with no effort anywhere becomes
      ``reasoning: {enabled: true}``.

Ruling (plan over scoped rule): providers.md says format translation happens
in the provider — with the single openai provider type there is no per-backend
home for it, and the effort policy already shapes the body in the funnel, so
the approved plan names this seam.

INVARIANT: the translation never gates — the 400-gate is the effort policy's
(apply_reasoning_effort, explicit client values only).
Why: two gates on one body would race for the same 400, and a translation
that refuses is a gate in disguise. Concretely: unknown effort values pass
through verbatim, and a malformed ``thinking`` (not
``{type: enabled|disabled}``) is left exactly where the client put it — for
every dialect except openai, where the field never exists and is dropped
whatever its shape.
"""
from typing import Any

from ..core.error_handling import ErrorType, create_error

# Wire dialects a provider entry may name; the first is the default because a
# third-party OpenAI-compat gateway must work with no config change.
REASONING_DIALECTS = ("openai", "deepseek", "openrouter")
DEFAULT_REASONING_DIALECT = "openai"

# dsh spells `max`; OpenRouter's reasoning.effort tops out at `high`. Anything
# not in the map passes through verbatim — the upstream judges its own vocabulary.
_OPENROUTER_EFFORT_MAP = {"low": "low", "medium": "medium", "high": "high", "max": "high"}
_THINKING_TYPES = ("enabled", "disabled")


def validate_reasoning_dialect(value: Any, provider_name: str | None = None) -> None:
    """Raise PROVIDER_CONFIG_ERROR unless ``value`` names a known dialect.

    Consumed by BaseProvider.__init__ (startup validation / reload veto), so a
    typo can never reach the funnel as a silent ``openai``.
    """
    if value not in REASONING_DIALECTS:
        raise create_error(
            ErrorType.PROVIDER_CONFIG_ERROR,
            error_details=(
                f"Unknown reasoning_dialect: {value!r} "
                f"(expected one of: {', '.join(REASONING_DIALECTS)})."
            ),
            provider_name=provider_name,
        )


def resolve_dialect(provider_config: Any) -> str:
    """Defensive read of a provider entry's dialect; absent/unknown -> default.

    Construction-time validation already rejected unknown values on the real
    path; mocked configs in tests bypass it, so the funnel re-reads tolerantly
    (same defensive pattern as parse_effort_policy on the request path).
    """
    dialect = (provider_config or {}).get("reasoning_dialect", DEFAULT_REASONING_DIALECT)
    return dialect if dialect in REASONING_DIALECTS else DEFAULT_REASONING_DIALECT


def _thinking_type(request_body: dict[str, Any]) -> str | None:
    """The thinking toggle when well-formed (``{type: enabled|disabled}``), else None."""
    thinking = request_body.get("thinking")
    if not isinstance(thinking, dict):
        return None
    thinking_type = thinking.get("type")
    return thinking_type if thinking_type in _THINKING_TYPES else None


def _translate_openrouter(request_body: dict[str, Any]) -> dict[str, Any]:
    """Re-nest the dsh wire shape into OpenRouter's ``reasoning`` object.

    Resolution order: an explicit ``disabled`` (thinking or effort ``off``)
    wins over everything and ships ``{enabled: false}``; an effort ships
    ``{effort: <mapped>}``; a bare enabled thinking ships ``{enabled: true}``
    only when no effort is declared anywhere (effort implies enabled).
    """
    thinking_type = _thinking_type(request_body)
    effort = request_body.get("reasoning_effort")
    effort_is_str = isinstance(effort, str)
    if thinking_type is None and not effort_is_str:
        return request_body

    reasoning = request_body.get("reasoning")
    if reasoning is None:
        reasoning = {}
    elif not isinstance(reasoning, dict):
        # Non-dict `reasoning` (client garbage): nowhere safe to write.
        return request_body

    if thinking_type == "disabled" or effort == "off":
        # Disabled wins: drop any effort declared in either location.
        reasoning.pop("effort", None)
        reasoning["enabled"] = False
    elif effort_is_str:
        reasoning["effort"] = _OPENROUTER_EFFORT_MAP.get(effort, effort)
    elif "effort" not in reasoning:
        reasoning["enabled"] = True

    if effort_is_str:
        del request_body["reasoning_effort"]
    if thinking_type is not None:
        del request_body["thinking"]
    request_body["reasoning"] = reasoning
    return request_body


def translate_reasoning_fields(
    request_body: dict[str, Any],
    provider_config: Any,
) -> dict[str, Any]:
    """Re-shape ``thinking`` / ``reasoning_effort`` per the provider's dialect.

    Runs on the dispatch funnel AFTER the effort policy, so the value that was
    gated legal is exactly what gets re-nested. Returns the (possibly mutated)
    body; a body carrying none of the fields is returned unchanged for every
    dialect.
    """
    dialect = resolve_dialect(provider_config)
    if dialect == "deepseek":
        # Native dialect: both fields stay exactly where the client put them.
        return request_body
    if dialect == "openai":
        # The dialect has no `thinking` field; dropping it whatever its shape
        # is the translation, not a mutation of client data.
        request_body.pop("thinking", None)
        return request_body
    return _translate_openrouter(request_body)
