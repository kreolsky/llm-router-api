"""Per-model reasoning effort policy: gate client values, inject the default.

ARCH: enforcement lives in the ONE funnel (BaseService._prepare_dispatch) so
every body-carrying endpoint — chat today, anything body-carrying later —
gets the policy by construction instead of per-service. The policy itself is
a models.yaml key, next to ``options:`` which already shapes the outgoing
body:

    reasoning_effort:
      allowed: [low, high, max]       # values permitted to reach the upstream
      default: high                   # optional; injected when the client sends none
      param: reasoning_effort         # wire location: reasoning_effort | reasoning.effort

Configured blocks carry no ``default`` today: the client-side default is the
harness's business (dsh materializes its adapter default), and ``medium`` is
avoided — dsh's effort vocabulary is off|low|high|max and a value it cannot
spell would 400 inside the harness before ever reaching the router.

Absent key => the field passes through untouched (today's behaviour). The
client value is read from BOTH dialects (``reasoning_effort`` and
``reasoning.effort`` — a harness picks its own) and, when allowed, is left
exactly where the client put it; only the injected default has a chosen
location (``param``). ``options.reasoning_effort`` still wins over the
injected default — options merge happens later in
providers/base.py _apply_model_config; a model carrying both is rejected at
load time by core/config_schema.py parse_model.
"""
from typing import Any

from ..core.config_schema import EFFORT_PARAMS, EffortPolicy, read_effort_param
from ..core.error_handling import ErrorType, create_error


def _client_efforts(request_body: dict[str, Any]) -> list[tuple[str, Any]]:
    """Every client-sent effort value present, as ``(wire location, value)`` pairs.

    INVARIANT: EVERY present dialect is returned, not the first one found.
    Why: a body carrying an allowed `reasoning_effort` next to a disallowed
    `reasoning.effort` would otherwise ship the disallowed value upstream —
    the gate has to see all of them to refuse any of them.

    INVARIANT: the location travels with the value.
    Why: the 400 must name the field the client actually sent; naming the other
    dialect points them at a parameter that is not in their request.

    A JSON null in either location counts as absent (unset), matching
    ``request_body.get`` semantics on the top level.
    """
    return [
        (param, value)
        for param in EFFORT_PARAMS
        if (value := read_effort_param(request_body, param)) is not None
    ]


def _render_value(value: Any) -> str:
    """The offending value as it appears in the 400 and in the log line.

    WHY truncated: the value is unvalidated client JSON and lands verbatim in
    both the error envelope and a WARNING; an allowed value is always a short
    string, so nothing legitimate is cut.
    """
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= 64 else text[:61] + "..."


def _inject_default(request_body: dict[str, Any], param: str, default: str) -> dict[str, Any]:
    """Write the default effort at ``param``'s location — never both, and
    never over client data (a non-dict ``reasoning`` value skips injection).
    """
    if param == "reasoning_effort":
        request_body["reasoning_effort"] = default
        return request_body
    reasoning = request_body.get("reasoning")
    if reasoning is None:
        reasoning = request_body["reasoning"] = {}
    elif not isinstance(reasoning, dict):
        # Non-dict `reasoning` (client garbage): nowhere safe to write.
        return request_body
    reasoning["effort"] = default
    return request_body


def apply_reasoning_effort(
    request_body: dict[str, Any],
    policy: EffortPolicy | None,
    **error_ctx: Any,
) -> dict[str, Any]:
    """Enforce the model's reasoning effort policy on a parsed request body.

    Returns the (possibly mutated) body: unchanged when the model carries no
    policy (``None`` — absent, or dropped at load), when the client sent an allowed value, or when there is no
    default to inject. Raises 400 invalid_parameter_value when a client value
    is outside ``allowed`` — fail-fast, not a clamp: silently downgrading a
    harness's ``max`` to ``high`` produces an unexplainable bill and no
    signal to the client.
    """
    if policy is None:
        return request_body

    client_values = _client_efforts(request_body)
    if client_values:
        for location, value in client_values:
            if value not in policy.allowed:
                raise create_error(
                    ErrorType.INVALID_PARAMETER_VALUE,
                    parameter_name=location,
                    parameter_value=_render_value(value),
                    allowed_values=", ".join(policy.allowed),
                    **error_ctx,
                )
        # Allowed: stays exactly where the client sent it — no relocation to
        # param's location, no second field in the other dialect.
        return request_body

    if policy.default is None:
        return request_body
    # WHY: the body is not passthrough (identity: passthrough covers headers
    # only — core/header_policy.py); ``model`` is already rewritten on this
    # same path and ``options:`` merges into the body for the same reason, so
    # injecting an opt-in per-model default is consistent. It does shade the
    # harness fingerprint the upstream sees — accepted because the key is
    # opt-in per model and nothing moves until an operator adds it.
    return _inject_default(request_body, policy.param, policy.default)
