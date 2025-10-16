"""
Error Logging Utility

This module provides centralized error logging functionality for consistent
error logging across the LLM Router project.
"""

import logging
from typing import Dict, Any, Optional
from .error_types import ErrorType, ErrorContext

logger = logging.getLogger("nnp-llm-router")


class ErrorLogger:
    """Centralized error logging utility."""
    
    @staticmethod
    def log_error(
        error_type: ErrorType,
        context: ErrorContext,
        original_exception: Optional[Exception] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log an error with standardized format."""
        
        log_extra = context.to_log_extra()
        
        # Add error-specific information
        log_extra["error_type"] = error_type.code
        log_extra["error_code"] = error_type.code
        log_extra["http_status_code"] = error_type.status_code
        
        if additional_data:
            log_extra.update(additional_data)
        
        # Format the log message
        log_message = f"{error_type.format_message(**context.__dict__)}"
        
        # Add original exception information if provided
        if original_exception:
            log_extra["original_exception"] = str(original_exception)
            log_extra["original_exception_type"] = type(original_exception).__name__
            
            # Log with stack trace for debugging
            logger.error(
                log_message,
                extra=log_extra,
                exc_info=True
            )
        else:
            logger.error(
                log_message,
                extra=log_extra
            )
    
    @staticmethod
    def log_provider_error(
        provider_name: str,
        error_details: str,
        status_code: int,
        context: ErrorContext,
        original_exception: Optional[Exception] = None
    ):
        """Log provider-specific errors."""
        
        log_extra = context.to_log_extra()
        log_extra.update({
            "provider_name": provider_name,
            "provider_error_details": error_details,
            "provider_status_code": status_code,
            "error_type": "provider_error",
            "log_type": "error"
        })
        
        if original_exception:
            log_extra["original_exception"] = str(original_exception)
            log_extra["original_exception_type"] = type(original_exception).__name__
        
        logger.error(
            f"Provider '{provider_name}' returned error {status_code}: {error_details}",
            extra=log_extra,
            exc_info=original_exception is not None
        )