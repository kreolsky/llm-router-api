"""
Simple logging utilities for the universal Logger.

This module contains minimal utility functions for the simplified logging system.
"""

import time
from typing import Dict, Any, Optional
from contextlib import contextmanager


@contextmanager
def timing_context(logger, operation: str, request_id: str, **kwargs):
    """
    Simple timing context for performance measurement.
    
    Args:
        logger: Logger instance
        operation: Operation name
        request_id: Request identifier
        **kwargs: Additional context data
    """
    start_time = time.time()
    try:
        yield
    finally:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"{operation} completed in {duration_ms}ms",
            extra={
                "request_id": request_id,
                "operation": operation,
                "duration_ms": duration_ms,
                **kwargs
            }
        )