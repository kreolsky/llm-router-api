"""The single error-envelope -> usage-stats walk.

ARCH: both places that read an OpenRouter-shaped error envelope to enrich the
per-request RequestStats holder — the HTTP exception handler
(src/api/main.py) and the stream processor's mid-stream error path
(src/services/chat_service/stream_processor.py) — call THIS function. Two
independent walks of one contract drift silently when the envelope gains a
field; one extractor cannot.
"""


def enrich_stats_from_envelope(stats, envelope, *, default_error_code=None):
    """Write error_code / error_message / provider_name into the stats holder.

    ``envelope`` is the full ``{"error": {...}}`` payload (an HTTPException
    detail dict or a framed stream error payload). Best-effort by design:

    - ``message`` writes error_message when present;
    - ``metadata.error_code`` writes error_code when truthy, else
      ``default_error_code`` applies (the stream passes
      "internal_server_error"; the HTTP handler passes nothing, keeping an
      error status with NULL error_code an expected shape);
    - ``metadata.provider_name`` fills provider_name only when the holder has
      none yet — the resolver usually set it before the error surfaced.
    """
    error = envelope.get("error") or {}
    if not isinstance(error, dict):
        return
    message = error.get("message")
    if message:
        stats.error_message = str(message)
    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        error_code = metadata.get("error_code")
        if error_code:
            stats.error_code = str(error_code)
        elif default_error_code:
            stats.error_code = default_error_code
        provider_name = metadata.get("provider_name")
        if provider_name and not stats.provider_name:
            stats.provider_name = str(provider_name)
    elif default_error_code and not stats.error_code:
        stats.error_code = default_error_code
