"""
Ultra-simple universal Logger for debugging and diagnostics.

This module provides a minimal Logger class focused on simplicity and
effective debugging capabilities when LOG_LEVEL=DEBUG.
"""

import logging
import time
import json
from typing import Dict, Any, Optional, Tuple
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
    
    def _process_kwargs(self, kwargs: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
        """
        Process kwargs to extract 'extra' and 'exc_info', and merge them correctly.
        Returns a tuple of (processed_kwargs, exc_info).
        """
        exc_info = kwargs.pop('exc_info', None)
        
        # Extract extra if it's in kwargs and merge it
        extra_input = kwargs.pop('extra', {})
        if isinstance(extra_input, dict):
            kwargs.update(extra_input)
            
        # Remove reserved keys that would cause KeyError in logging
        reserved_keys = [
            'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
            'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'msg', 'name', 'pathname', 'process', 'processName',
            'relativeCreated', 'stack_info', 'thread', 'threadName'
        ]
        for key in reserved_keys:
            if key in kwargs:
                # Prefix reserved keys to avoid conflict
                kwargs[f"ctx_{key}"] = kwargs.pop(key)
                
        return kwargs, exc_info

    def info(self, message: str, **kwargs):
        """Log an info message."""
        processed_kwargs, _ = self._process_kwargs(kwargs)
        if processed_kwargs:
            self._logger.info(message, extra=processed_kwargs)
        else:
            self._logger.info(message)
    
    def debug(self, message: str, **kwargs):
        """Log a debug message."""
        processed_kwargs, _ = self._process_kwargs(kwargs)
        if processed_kwargs:
            self._logger.debug(message, extra=processed_kwargs)
        else:
            self._logger.debug(message)
    
    def warning(self, message: str, **kwargs):
        """Log a warning message."""
        processed_kwargs, _ = self._process_kwargs(kwargs)
        if processed_kwargs:
            self._logger.warning(message, extra=processed_kwargs)
        else:
            self._logger.warning(message)
    
    def error(self, message: str, **kwargs):
        """Log an error message."""
        processed_kwargs, exc_info = self._process_kwargs(kwargs)
        if exc_info is None:
            exc_info = True
            
        if processed_kwargs:
            self._logger.error(message, extra=processed_kwargs, exc_info=exc_info)
        else:
            self._logger.error(message, exc_info=exc_info)
    
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
    
    def _truncate_large_values(self, data: Any, max_length: int = 1000) -> Any:
        """
        Recursively truncate large strings in a dictionary or list.
        """
        if isinstance(data, str):
            if len(data) > max_length:
                return data[:max_length] + f"... [truncated, total length: {len(data)}]"
            return data
        elif isinstance(data, dict):
            return {k: self._truncate_large_values(v, max_length) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._truncate_large_values(i, max_length) for i in data]
        return data

    def debug_data(self, title: str, data: Any, request_id: str, **kwargs):
        """Log debug data with full details when LOG_LEVEL=DEBUG."""
        if not self.is_debug_enabled():
            return
        
        # Truncate large values to avoid memory issues and log bloat
        truncated_data = self._truncate_large_values(data)
        
        # Format data for logging
        if isinstance(truncated_data, dict):
            data_str = json.dumps(truncated_data, indent=2, ensure_ascii=False)
        else:
            data_str = str(truncated_data)
        
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