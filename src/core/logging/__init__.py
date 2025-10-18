"""
Ultra-simple logging infrastructure for the LLM Router.

Provides a minimal Logger class focused on effective debugging and diagnostics.
"""

from .logger import logger, Logger
from .config import setup_logging
from .utils import timing_context

# Export only the essential components
__all__ = [
    'logger',
    'Logger',
    'setup_logging',
    'timing_context'
]