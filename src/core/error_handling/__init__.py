"""
Error Handling Module

This module provides centralized error handling utilities for the LLM Router project.
It includes standardized error types, logging, and exception handling to eliminate
code duplication and ensure consistent error responses across all services.

Components:
- ErrorType: Enumeration of standard error types
- ErrorContext: Context information for error handling
- ErrorHandler: Main error handling utility
- ErrorLogger: Centralized error logging utility
"""

from .error_types import ErrorType, ErrorContext
from .error_handler import ErrorHandler
from .error_logger import ErrorLogger

__all__ = [
    'ErrorType',
    'ErrorContext', 
    'ErrorHandler',
    'ErrorLogger'
]