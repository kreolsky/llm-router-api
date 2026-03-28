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
        self._logger = setup_logging()

    def is_debug_enabled(self) -> bool:
        return self._logger.isEnabledFor(logging.DEBUG)

    def _process_kwargs(self, kwargs: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
        """Extract extra/exc_info from kwargs and prefix reserved logging keys with ctx_.

        The stdlib logging module reserves certain keys in the extra dict (e.g. 'args',
        'name', 'msg'). Passing them directly causes KeyError, so they are prefixed.
        """
        exc_info = kwargs.pop('exc_info', None)

        extra_input = kwargs.pop('extra', {})
        if isinstance(extra_input, dict):
            kwargs.update(extra_input)

        # WHY: stdlib logging reserves certain keys in extra dict — passing them causes KeyError
        reserved_keys = [
            'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
            'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'msg', 'name', 'pathname', 'process', 'processName',
            'relativeCreated', 'stack_info', 'thread', 'threadName'
        ]
        for key in reserved_keys:
            if key in kwargs:
                kwargs[f"ctx_{key}"] = kwargs.pop(key)
                
        return kwargs, exc_info

    def info(self, message: str, **kwargs):
        processed_kwargs, _ = self._process_kwargs(kwargs)
        if processed_kwargs:
            self._logger.info(message, extra=processed_kwargs)
        else:
            self._logger.info(message)

    def debug(self, message: str, **kwargs):
        processed_kwargs, _ = self._process_kwargs(kwargs)
        if processed_kwargs:
            self._logger.debug(message, extra=processed_kwargs)
        else:
            self._logger.debug(message)

    def warning(self, message: str, **kwargs):
        processed_kwargs, _ = self._process_kwargs(kwargs)
        if processed_kwargs:
            self._logger.warning(message, extra=processed_kwargs)
        else:
            self._logger.warning(message)

    def error(self, message: str, **kwargs):
        processed_kwargs, exc_info = self._process_kwargs(kwargs)
        if exc_info is None:
            exc_info = False
            
        if processed_kwargs:
            self._logger.error(message, extra=processed_kwargs, exc_info=exc_info)
        else:
            self._logger.error(message, exc_info=exc_info)
    
    def _truncate_large_values(self, data: Any, max_length: int = 1000) -> Any:
        """Recursively truncate large strings in nested data structures."""
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

        truncated_data = self._truncate_large_values(data)

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
    
    @contextmanager
    def request_context(self, operation: str, request_id: str, **kwargs):
        """Context manager that logs request start, completion, and errors."""
        start_time = time.time()
        self.info(f"Started: {operation}", request_id=request_id, **kwargs)

        try:
            yield
        except Exception as e:
            self.error(
                f"{operation} failed: {str(e)}",
                request_id=request_id,
                **kwargs
            )
            raise
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            self.info(
                f"Completed: {operation} | duration={duration_ms}ms",
                request_id=request_id,
                **kwargs
            )


# Create default logger instance
logger = Logger()