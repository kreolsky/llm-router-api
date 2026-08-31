"""Centralized error handling: types and factory function."""

from .envelope import enrich_stats_from_envelope
from .error_handler import create_error, create_provider_http_error, log_provider_error
from .error_types import ErrorType

__all__ = ['ErrorType', 'create_error', 'create_provider_http_error', 'enrich_stats_from_envelope', 'log_provider_error']
