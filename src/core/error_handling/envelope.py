"""The single error-envelope -> usage-stats walk.

ARCH: both places that read an OpenRouter-shaped error envelope to enrich the
per-request RequestStats holder — the HTTP exception handler
(src/api/main.py) and the stream processor's mid-stream error path
(src/services/chat_service/stream_processor.py) — call THIS function. Two
independent walks of one contract drift silently when the envelope gains a
field; one extractor cannot.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..usage_db import RequestStats


def enrich_stats_from_envelope(
    stats: "RequestStats",
    envelope: dict[str, Any],
    *,
    default_error_code: str | None = None,
    overwrite: bool = False,
) -> None:
    """Write error_code / error_message / provider_name into the stats holder.

    ``envelope`` is the full ``{"error": {...}}`` payload (an HTTPException
    detail dict or a framed stream error payload).

    The HTTP handler enriches best-effort (``overwrite=False``): only truthy
    values are written, so an envelope without metadata.error_code leaves
    error_code NULL — an error status with NULL error_code is an expected
    shape, the UI groups it under "—".

    INVARIANT: with overwrite=True the envelope is AUTHORITATIVE for
    error_code and error_message — both assigned, a missing message clears.
    Why: the stream processor's payload IS the terminal error for that
    request, so a value enriched earlier must not survive it — the usage row
    has to keep recording "internal_server_error" for a generic mid-stream
    failure, which is what the mid-stream path did before the two walks were
    merged into this one.

    provider_name is never overwritten either way — it is filled only when
    the holder has none yet, since the resolver usually set it before the
    error surfaced.
    """
    error = envelope.get("error") or {}
    if not isinstance(error, dict):
        error = {}
    message = error.get("message")
    if message:
        stats.error_message = str(message)
    elif overwrite:
        stats.error_message = None

    metadata = error.get("metadata")
    error_code = metadata.get("error_code") if isinstance(metadata, dict) else None
    if error_code:
        stats.error_code = str(error_code)
    elif default_error_code and (overwrite or not stats.error_code):
        stats.error_code = default_error_code

    if isinstance(metadata, dict):
        provider_name = metadata.get("provider_name")
        if provider_name and not stats.provider_name:
            stats.provider_name = str(provider_name)
