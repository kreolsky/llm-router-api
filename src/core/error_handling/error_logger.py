"""
Error Logging Utility

This module provides centralized error logging functionality for consistent
error logging across the LLM Router project.
"""

from typing import Dict, Any, Optional
import json
import re
from .error_types import ErrorType, ErrorContext
from ..logging.config import setup_logging


class ErrorLogger:
    """Единый логгер ошибок, использующий общую систему."""
    
    @staticmethod
    def _decode_unicode_escapes(text):
        """
        Decode Unicode escape sequences in error messages.
        
        Args:
            text (str): Text that may contain Unicode escape sequences
            
        Returns:
            str: Text with Unicode escape sequences decoded to actual characters
        """
        if not text:
            return text
            
        # Try to decode JSON with Unicode escapes
        try:
            if '\\u' in text:
                # Check if it's a JSON string
                if text.startswith('{') and text.endswith('}'):
                    decoded = json.loads(text)
                    if isinstance(decoded, dict):
                        return json.dumps(decoded, ensure_ascii=False)
                # For non-JSON strings, use encode-decode
                return text.encode().decode('unicode_escape')
        except (json.JSONDecodeError, ValueError, UnicodeError):
            pass
        
        # Fallback: manually decode Unicode escape sequences
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
        """Получить логгер из единой системы."""
        return setup_logging()
    
    @staticmethod
    def log_error(
        error_type: ErrorType,
        context: ErrorContext,
        original_exception: Optional[Exception] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Логировать ошибку с использованием единой системы."""
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