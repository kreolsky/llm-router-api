"""Passthrough header whitelist: the default harness set and its config override.

ARCH: which client headers an `identity`-enabled provider forwards upstream is
data, not code. The default set below covers
the harnesses we actually see — opencode and Kilo Code, which is an opencode
fork and sends the same session headers (`ses_*` ids, x-session-affinity) plus
its own `Kilo-Code/<v>` User-Agent. A provider may replace the whole set via
`passthrough_headers:` in providers.yaml; it REPLACES rather than extends, so
an operator can narrow the set and not only widen it.

Spec entries are header names, matched case-insensitively; a trailing `*` makes
one a prefix pattern (`x-stainless-*`). The spelling written in the spec is the
spelling sent upstream — casing is part of a harness fingerprint.
"""
# SYSTEM: identity-headers — passthrough header whitelist and its override

from typing import Dict, Iterable, List, Optional, Tuple

# Canonical spelling as opencode/Kilo send them; `*` = prefix match.
DEFAULT_PASSTHROUGH_HEADERS: Tuple[str, ...] = (
    "User-Agent",
    "X-Session-Id",
    "x-session-affinity",
    "x-parent-session-id",
    "anthropic-beta",
    "x-stainless-*",
)

# Compiled spec: (exact lower-name -> spelling to send, prefix patterns)
PassthroughSpec = Tuple[Dict[str, str], Tuple[Tuple[str, str], ...]]


def compile_passthrough_spec(spec: Optional[Iterable[str]] = None) -> PassthroughSpec:
    """Compile a header-name spec into (exact map, prefix patterns).

    Raises ValueError on a malformed entry so a bad providers.yaml fails at
    provider construction (startup validation), not on the first request.
    """
    names: List[str] = list(DEFAULT_PASSTHROUGH_HEADERS if spec is None else spec)
    exact: Dict[str, str] = {}
    prefixes: List[Tuple[str, str]] = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"passthrough_headers entry must be a non-empty string, got {name!r}")
        name = name.strip()
        if name.endswith("*"):
            stem = name[:-1]
            if not stem:
                raise ValueError("passthrough_headers entry '*' would forward every client header")
            prefixes.append((stem.lower(), stem))  # spelling unused: see match_passthrough
        else:
            exact[name.lower()] = name
    return exact, tuple(prefixes)


def match_passthrough(name: str, spec: PassthroughSpec) -> Optional[str]:
    """Return the spelling to send upstream for a client header, or None."""
    exact, prefixes = spec
    low = name.lower()
    canonical = exact.get(low)
    if canonical is not None:
        return canonical
    for stem_low, _stem in prefixes:
        if low.startswith(stem_low):
            # WHY: a prefix pattern cannot know the tail's casing, so the
            # client's own spelling is forwarded verbatim.
            return name
    return None
