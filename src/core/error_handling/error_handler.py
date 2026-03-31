"""Single function for creating standardized HTTPExceptions with logging."""

import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException

from .error_types import ErrorType
from ...utils.unicode import decode_unicode_escapes

_logger = logging.getLogger("llm_router")


def create_error(
    error_type: ErrorType,
    original_exception: Optional[Exception] = None,
    **context
) -> HTTPException:
    """Create a standardized HTTPException with logging.

    All context fields (request_id, user_id, model_id, provider_name, etc.)
    are passed as kwargs and used for both message formatting and log extras.
    """
    error_detail = error_type.create_error_detail(**context)
    error_detail["error"]["code"] = error_type.status_code

    log_extra = {"log_type": "error", "error_type": error_type.code}
    for key in ("request_id", "user_id", "model_id", "provider_name", "endpoint_path"):
        if context.get(key):
            log_extra[key] = context[key]

    message = error_type.format_message(**context)

    if original_exception:
        log_extra["original_exception"] = str(original_exception)
        log_extra["original_exception_type"] = type(original_exception).__name__
        _logger.error(message, extra=log_extra, exc_info=True)
    else:
        _logger.error(message, extra=log_extra)

    return HTTPException(status_code=error_type.status_code, detail=error_detail)


def log_provider_error(
    provider_name: str,
    error_details: str,
    status_code: int,
    original_exception: Optional[Exception] = None,
    **context
) -> None:
    """Log a provider-specific HTTP error with Unicode decoding."""
    decoded = decode_unicode_escapes(error_details)

    log_extra = {
        "log_type": "error",
        "error_type": "provider_error",
        "provider_name": provider_name,
        "provider_error_details": decoded,
        "provider_status_code": status_code,
    }
    for key in ("request_id", "user_id", "model_id"):
        if context.get(key):
            log_extra[key] = context[key]

    if original_exception:
        log_extra["original_exception"] = str(original_exception)
        log_extra["original_exception_type"] = type(original_exception).__name__

    _logger.error(
        f"Provider '{provider_name}' returned error {status_code}: {decoded}",
        extra=log_extra,
        exc_info=original_exception is not None
    )
