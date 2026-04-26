"""Header masking helpers for safe debug logging."""
from typing import Dict

_SENSITIVE_HEADERS = {"authorization", "x-api-key", "api-key"}


def mask_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of headers with sensitive values masked.

    Sensitive headers (case-insensitive: Authorization, x-api-key, api-key)
    are replaced with '****<last4>' so logs never contain raw credentials.
    """
    if not headers:
        return {}
    masked = {}
    for k, v in headers.items():
        if k.lower() in _SENSITIVE_HEADERS and isinstance(v, str) and v:
            tail = v[-4:] if len(v) >= 4 else ""
            masked[k] = f"****{tail}"
        else:
            masked[k] = v
    return masked
