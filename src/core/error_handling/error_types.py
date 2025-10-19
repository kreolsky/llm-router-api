"""
Error Types and Context Definitions

This module defines standardized error types and context information for
consistent error handling across the LLM Router project.
"""

from enum import Enum
from typing import Dict, Any, Optional
from fastapi import HTTPException, status


class ErrorType(Enum):
    """Enumeration of standard error types in the system."""
    
    # Validation Errors (400)
    MODEL_NOT_SPECIFIED = ("model_not_specified", status.HTTP_400_BAD_REQUEST, "Model not specified in request")
    INVALID_REQUEST_FORMAT = ("invalid_request_format", status.HTTP_400_BAD_REQUEST, "Invalid request format")
    MISSING_REQUIRED_FIELD = ("missing_required_field", status.HTTP_400_BAD_REQUEST, "Missing required field: {field_name}")
    
    # Authorization Errors (401)
    MISSING_API_KEY = ("missing_api_key", status.HTTP_401_UNAUTHORIZED, "API key missing")
    INVALID_API_KEY = ("invalid_api_key", status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    
    # Permission Errors (403)
    MODEL_NOT_ALLOWED = ("model_not_allowed", status.HTTP_403_FORBIDDEN, "Model '{model_id}' is not available for your account")
    ENDPOINT_NOT_ALLOWED = ("endpoint_not_allowed", status.HTTP_403_FORBIDDEN, "Access to endpoint '{endpoint_path}' is not allowed")
    
    # Not Found Errors (404)
    MODEL_NOT_FOUND = ("model_not_found", status.HTTP_404_NOT_FOUND, "Model '{model_id}' not found in configuration")
    PROVIDER_NOT_FOUND = ("provider_not_found", status.HTTP_404_NOT_FOUND, "Provider '{provider_name}' not found for model '{model_id}'")
    
    # Server Errors (500)
    PROVIDER_CONFIG_ERROR = ("provider_config_error", status.HTTP_500_INTERNAL_SERVER_ERROR, "Provider configuration error: {error_details}")
    INTERNAL_SERVER_ERROR = ("internal_server_error", status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error: {error_details}")
    SERVER_CONFIG_ERROR = ("server_config_error", status.HTTP_500_INTERNAL_SERVER_ERROR, "Server configuration error: {error_details}")
    
    # Service Unavailable (503)
    SERVICE_UNAVAILABLE = ("service_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE, "Could not connect to service: {error_details}")
    
    # Provider Errors (dynamic status codes)
    PROVIDER_HTTP_ERROR = ("provider_http_error", None, "Provider error: {error_details}")
    PROVIDER_NETWORK_ERROR = ("provider_network_error", status.HTTP_500_INTERNAL_SERVER_ERROR, "Network error communicating with provider: {error_details}")
    PROVIDER_RATE_LIMIT_ERROR = ("rate_limit_exceeded", status.HTTP_429_TOO_MANY_REQUESTS, "Provider rate limit exceeded (429 Too Many Requests). Please retry after a delay.")
    PROVIDER_STREAM_ERROR = ("provider_stream_error", None, "Provider streaming error: {error_details}")

    def __init__(self, code: str, status_code: Optional[int], message_template: str):
        self.code = code
        self.status_code = status_code
        self.message_template = message_template
    
    def format_message(self, **kwargs) -> str:
        """Format the error message with provided parameters."""
        try:
            return self.message_template.format(**kwargs)
        except KeyError as e:
            # Fallback to template if formatting fails
            return self.message_template
    
    def create_error_detail(self, **kwargs) -> Dict[str, Any]:
        """Create standardized error detail dictionary."""
        return {
            "error": {
                "message": self.format_message(**kwargs),
                "code": self.code
            }
        }


class ErrorContext:
    """Context information for error handling."""
    
    def __init__(
        self,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        model_id: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        provider_name: Optional[str] = None,
        **additional_context
    ):
        self.request_id = request_id
        self.user_id = user_id
        self.model_id = model_id
        self.endpoint_path = endpoint_path
        self.provider_name = provider_name
        self.additional_context = additional_context
    
    def to_log_extra(self) -> Dict[str, Any]:
        """Convert context to logging extra dictionary."""
        extra = {
            "log_type": "error"
        }
        
        if self.request_id:
            extra["request_id"] = self.request_id
        if self.user_id:
            extra["user_id"] = self.user_id
        if self.model_id:
            extra["model_id"] = self.model_id
        if self.endpoint_path:
            extra["endpoint_path"] = self.endpoint_path
        if self.provider_name:
            extra["provider_name"] = self.provider_name
        
        extra.update(self.additional_context)
        return extra