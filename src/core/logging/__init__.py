"""
Core logging infrastructure for the LLM Router.

This module provides centralized logging utilities to replace repetitive logging patterns
across the codebase while maintaining identical log output formats.
"""

from .config import setup_logging
from .logger import default_app_logger as logger
from .utils import RequestLogger, DebugLogger, PerformanceLogger, StreamingLogger
from .logger import Logger

# Export main components for easy import
__all__ = [
    'logger',
    'setup_logging',
    'RequestLogger',
    'DebugLogger',
    'PerformanceLogger',
    'StreamingLogger',
    'Logger'
]