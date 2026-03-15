"""Centralized error logging with Unicode decoding."""

from typing import Dict, Any, Optional
import json
import re
from .error_types import ErrorType, ErrorContext
from ..logging.config import setup_logging


class ErrorLogger:
    """Unified error logger using the shared logging system."""

    @staticmethod
    def _decode_unicode_escapes(text):
        """Decode \\uXXXX escape sequences in provider error messages.

        Provider APIs return errors in mixed encodings, so three strategies
        are tried in order until one succeeds.
        """
        if not text:
            return text

        try:
            if '\\u' in text:
                # WHY: JSON objects with \u escapes decode cleanly via json roundtrip
                if text.startswith('{') and text.endswith('}'):
                    decoded = json.loads(text)
                    if isinstance(decoded, dict):
                        return json.dumps(decoded, ensure_ascii=False)
                # WHY: plain strings with \u escapes decode via Python's unicode_escape codec
                return text.encode().decode('unicode_escape')
        except (json.JSONDecodeError, ValueError, UnicodeError):
            pass

        # WHY: fallback regex for texts where neither JSON parse nor codec works
        unicode_pattern = re.compile(r'\\u([0-9a-fA-F]{4})')
        def replace_unicode(match):
            hex_code = match.group(1)
            try:
                return chr(int(hex_code, 16))
            except ValueError:
                return match.group(0)
        
        return unicode_pattern.sub(replace_unicode, text)
    
    @staticmethod
    def _get_logger():
        return setup_logging()
    
    @staticmethod
    def log_error(
        error_type: ErrorType,
        context: ErrorContext,
        original_exception: Optional[Exception] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log an error with unified formatting."""
        logger = ErrorLogger._get_logger()
        
        log_extra = context.to_log_extra()
        log_extra["error_type"] = error_type.code
        log_extra["error_code"] = error_type.code
        log_extra["http_status_code"] = error_type.status_code
        
        if additional_data:
            log_extra.update(additional_data)
        
        log_message = f"{error_type.format_message(**context.__dict__)}"
        
        if original_exception:
            log_extra["original_exception"] = str(original_exception)
            log_extra["original_exception_type"] = type(original_exception).__name__
            logger.error(log_message, extra=log_extra, exc_info=True)
        else:
            logger.error(log_message, extra=log_extra)
    
    @staticmethod
    def log_provider_error(
        provider_name: str,
        error_details: str,
        status_code: int,
        context: ErrorContext,
        original_exception: Optional[Exception] = None
    ):
        """Log provider-specific errors."""
        logger = ErrorLogger._get_logger()
        
        # Decode Unicode escape sequences in error details
        decoded_error_details = ErrorLogger._decode_unicode_escapes(error_details)
        
        log_extra = context.to_log_extra()
        log_extra.update({
            "provider_name": provider_name,
            "provider_error_details": decoded_error_details,
            "provider_status_code": status_code,
            "error_type": "provider_error",
            "log_type": "error"
        })
        
        if original_exception:
            log_extra["original_exception"] = str(original_exception)
            log_extra["original_exception_type"] = type(original_exception).__name__
        
        logger.error(
            f"Provider '{provider_name}' returned error {status_code}: {decoded_error_details}",
            extra=log_extra,
            exc_info=original_exception is not None
        )