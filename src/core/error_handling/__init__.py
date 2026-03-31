"""Centralized error handling: types and factory function."""

from .error_types import ErrorType
from .error_handler import create_error, log_provider_error

__all__ = ['ErrorType', 'create_error', 'log_provider_error']
