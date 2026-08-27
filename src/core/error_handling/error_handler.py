"""Standardized HTTPExceptions creation and provider error logging."""

from typing import Optional
from fastapi import HTTPException

from ..logging import logger
from .error_types import ErrorType
from ...utils.unicode import decode_unicode_escapes


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
        logger.error(message, extra=log_extra, exc_info=True)
    else:
        logger.error(message, extra=log_extra)

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

    logger.error(
        f"Provider '{provider_name}' returned error {status_code}: {decoded}",
        extra=log_extra,
        exc_info=original_exception is not None
    )


def create_provider_http_error(
    status_code: int,
    message: str,
    provider_name: str,
    raw: str,
    request_id: Optional[str] = None,
    original_exception: Optional[Exception] = None,
) -> HTTPException:
    """Build a provider passthrough HTTPException with dynamic status code.

    Uses the OpenRouter error shape ({"error": {"code", "message", "metadata"}})
    and logs through the unified provider error channel. The status code is
    dynamic (sourced from the upstream response) so it cannot be an ErrorType.
    """
    log_provider_error(
        provider_name=provider_name,
        error_details=raw,
        status_code=status_code,
        original_exception=original_exception,
        request_id=request_id,
    )

    error_detail = {
        "error": {
            "code": status_code,
            "message": message,
            "metadata": {
                "provider_name": provider_name,
                "raw": raw,
                "error_code": "provider_http_error",
            },
        }
    }
    return HTTPException(status_code=status_code, detail=error_detail)
