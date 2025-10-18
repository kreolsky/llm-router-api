"""
Ultra-simple universal Logger for debugging and diagnostics.

This module provides a minimal Logger class focused on simplicity and
effective debugging capabilities when LOG_LEVEL=DEBUG.
"""

import logging
import time
import json
from typing import Dict, Any, Optional
from contextlib import contextmanager
from .config import setup_logging


class Logger:
    """
    Ultra-simple Logger for effective debugging and diagnostics.
    
    Focus on simplicity while maintaining comprehensive debug capabilities
    when LOG_LEVEL=DEBUG is enabled.
    """
    
    def __init__(self):
        """Initialize the Logger with default configuration."""
        self._logger = setup_logging()
    
    def is_debug_enabled(self) -> bool:
        """Check if debug logging is enabled."""
        return self._logger.isEnabledFor(logging.DEBUG)
    
    def info(self, message: str, **kwargs):
        """Log an info message."""
        if kwargs:
            self._logger.info(message, extra=kwargs)
        else:
            self._logger.info(message)
    
    def debug(self, message: str, **kwargs):
        """Log a debug message."""
        if kwargs:
            self._logger.debug(message, extra=kwargs)
        else:
            self._logger.debug(message)
    
    def warning(self, message: str, **kwargs):
        """Log a warning message."""
        if kwargs:
            self._logger.warning(message, extra=kwargs)
        else:
            self._logger.warning(message)
    
    def error(self, message: str, **kwargs):
        """Log an error message."""
        if kwargs:
            self._logger.error(message, extra=kwargs, exc_info=True)
        else:
            self._logger.error(message, exc_info=True)
    
    def request(self, operation: str, request_id: str, **kwargs):
        """Log a request with context."""
        message_parts = [f"Request: {operation}"]
        if 'model_id' in kwargs:
            message_parts.append(f"model={kwargs['model_id']}")
        if 'provider_name' in kwargs:
            message_parts.append(f"provider={kwargs['provider_name']}")
        
        message = " | ".join(message_parts)
        self.info(message, request_id=request_id, **kwargs)
    
    def response(self, operation: str, request_id: str, status_code: int = 200, **kwargs):
        """Log a response with context."""
        message_parts = [f"Response: {operation}", f"status={status_code}"]
        if 'processing_time_ms' in kwargs:
            message_parts.append(f"time={kwargs['processing_time_ms']}ms")
        
        message = " | ".join(message_parts)
        self.info(message, request_id=request_id, **kwargs)
    
    def debug_data(self, title: str, data: Any, request_id: str, **kwargs):
        """Log debug data with full details when LOG_LEVEL=DEBUG."""
        if not self.is_debug_enabled():
            return
        
        # Format data for logging
        if isinstance(data, dict):
            data_str = json.dumps(data, indent=2, ensure_ascii=False)
        else:
            data_str = str(data)
        
        message = f"DEBUG: {title}"
        if 'component' in kwargs:
            message += f" | component={kwargs['component']}"
        if 'data_flow' in kwargs:
            message += f" | flow={kwargs['data_flow']}"
        
        self.debug(f"{message}\n{data_str}", request_id=request_id, **kwargs)
    
    def performance(self, operation: str, start_time: float, request_id: str, **kwargs):
        """Log performance metrics."""
        duration_ms = int((time.time() - start_time) * 1000)
        message_parts = [f"Performance: {operation}", f"duration={duration_ms}ms"]
        
        message = " | ".join(message_parts)
        self.info(message, request_id=request_id, duration_ms=duration_ms, **kwargs)
    
    @contextmanager
    def request_context(self, operation: str, request_id: str, **kwargs):
        """
        Simple context manager for request-scoped logging.
        
        Automatically logs request start, completion, and handles errors.
        """
        start_time = time.time()
        
        # Log request start
        self.request(operation=operation, request_id=request_id, **kwargs)
        
        try:
            yield
        except Exception as e:
            # Log error
            self.error(
                f"{operation} failed: {str(e)}",
                request_id=request_id,
                **kwargs
            )
            raise
        finally:
            # Log completion
            duration_ms = int((time.time() - start_time) * 1000)
            self.info(
                f"Completed: {operation} | duration={duration_ms}ms",
                request_id=request_id,
                **kwargs
            )


# Create default logger instance
logger = Logger()