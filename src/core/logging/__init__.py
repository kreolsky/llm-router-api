"""
Ultra-simple logging infrastructure for the LLM Router.

Provides a minimal Logger class focused on effective debugging and diagnostics.
"""

from .config import setup_logging
from .logger import Logger

_logger_instance = None

def get_logger():
    """Return the singleton Logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
    return _logger_instance

logger = get_logger()

__all__ = ['logger', 'Logger', 'setup_logging']