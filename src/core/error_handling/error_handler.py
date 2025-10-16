"""
Main Error Handler

This module provides the main error handling utility for creating standardized
HTTPExceptions with proper logging across the LLM Router project.
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException
import httpx

from .error_types import ErrorType, ErrorContext
from .error_logger import ErrorLogger


class ErrorHandler:
    """Centralized error handling utility."""
    
    @staticmethod
    def create_http_exception(
        error_type: ErrorType,
        context: Optional[ErrorContext] = None,
        original_exception: Optional[Exception] = None,
        log_error: bool = True,
        **format_kwargs
    ) -> HTTPException:
        """
        Create a standardized HTTPException with proper logging.
        
        Args:
            error_type: The type of error to create
            context: Error context information
            original_exception: Original exception that caused this error
            log_error: Whether to log the error
            **format_kwargs: Additional kwargs for message formatting
            
        Returns:
            HTTPException with standardized format
        """
        
        # Use provided context or create empty one
        if context is None:
            context = ErrorContext()
        
        # Merge format kwargs with context
        format_dict = {**context.__dict__, **format_kwargs}
        
        # Create error detail
        error_detail = error_type.create_error_detail(**format_dict)
        
        # Handle provider errors with dynamic status codes
        status_code = error_type.status_code
        if error_type == ErrorType.PROVIDER_HTTP_ERROR and original_exception:
            if hasattr(original_exception, 'response') and hasattr(original_exception.response, 'status_code'):
                status_code = original_exception.response.status_code
                # Update error detail with provider-specific code
                error_detail["error"]["code"] = f"provider_http_error_{status_code}"
        
        # Log the error if requested
        if log_error:
            additional_data = {"error_detail": error_detail}
            ErrorLogger.log_error(
                error_type=error_type,
                context=context,
                original_exception=original_exception,
                additional_data=additional_data
            )
        
        # Create and return HTTPException
        return HTTPException(
            status_code=status_code,
            detail=error_detail
        )
    
    @staticmethod
    def handle_model_not_specified(context: ErrorContext) -> HTTPException:
        """Handle model not specified error."""
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.MODEL_NOT_SPECIFIED,
            context=context
        )
    
    @staticmethod
    def handle_model_not_allowed(model_id: str, context: ErrorContext) -> HTTPException:
        """Handle model not allowed error."""
        context.model_id = model_id
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.MODEL_NOT_ALLOWED,
            context=context
        )
    
    @staticmethod
    def handle_model_not_found(model_id: str, context: ErrorContext) -> HTTPException:
        """Handle model not found error."""
        context.model_id = model_id
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.MODEL_NOT_FOUND,
            context=context
        )
    
    @staticmethod
    def handle_provider_not_found(provider_name: str, model_id: str, context: ErrorContext) -> HTTPException:
        """Handle provider not found error."""
        context.provider_name = provider_name
        context.model_id = model_id
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.PROVIDER_NOT_FOUND,
            context=context
        )
    
    @staticmethod
    def handle_provider_config_error(error_details: str, context: ErrorContext, original_exception: Optional[Exception] = None) -> HTTPException:
        """Handle provider configuration error."""
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.PROVIDER_CONFIG_ERROR,
            context=context,
            original_exception=original_exception,
            error_details=error_details
        )
    
    @staticmethod
    def handle_provider_http_error(
        original_exception: httpx.HTTPStatusError,
        context: ErrorContext,
        provider_name: Optional[str] = None
    ) -> HTTPException:
        """Handle provider HTTP errors."""
        if provider_name:
            context.provider_name = provider_name
        
        error_details = original_exception.response.text
        ErrorLogger.log_provider_error(
            provider_name=provider_name or "unknown",
            error_details=error_details,
            status_code=original_exception.response.status_code,
            context=context,
            original_exception=original_exception
        )
        
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.PROVIDER_HTTP_ERROR,
            context=context,
            original_exception=original_exception,
            log_error=False  # Already logged above
        )
    
    @staticmethod
    def handle_provider_network_error(
        original_exception: httpx.RequestError,
        context: ErrorContext,
        provider_name: Optional[str] = None
    ) -> HTTPException:
        """Handle provider network errors."""
        if provider_name:
            context.provider_name = provider_name
        
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.PROVIDER_NETWORK_ERROR,
            context=context,
            original_exception=original_exception,
            error_details=str(original_exception)
        )
    
    @staticmethod
    def handle_internal_server_error(
        error_details: str,
        context: ErrorContext,
        original_exception: Optional[Exception] = None
    ) -> HTTPException:
        """Handle internal server errors."""
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.INTERNAL_SERVER_ERROR,
            context=context,
            original_exception=original_exception,
            error_details=error_details
        )
    
    @staticmethod
    def handle_auth_errors(
        auth_type: str,
        context: ErrorContext,
        original_exception: Optional[Exception] = None
    ) -> HTTPException:
        """Handle authentication errors."""
        if auth_type == "missing_api_key":
            return ErrorHandler.create_http_exception(
                error_type=ErrorType.MISSING_API_KEY,
                context=context,
                original_exception=original_exception
            )
        elif auth_type == "invalid_api_key":
            return ErrorHandler.create_http_exception(
                error_type=ErrorType.INVALID_API_KEY,
                context=context,
                original_exception=original_exception
            )
        else:
            return ErrorHandler.handle_internal_server_error(
                error_details=f"Authentication error: {auth_type}",
                context=context,
                original_exception=original_exception
            )
    
    @staticmethod
    def handle_endpoint_not_allowed(endpoint_path: str, context: ErrorContext) -> HTTPException:
        """Handle endpoint not allowed error."""
        context.endpoint_path = endpoint_path
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.ENDPOINT_NOT_ALLOWED,
            context=context
        )
    
    @staticmethod
    def handle_service_unavailable(
        error_details: str,
        context: ErrorContext,
        original_exception: Optional[Exception] = None
    ) -> HTTPException:
        """Handle service unavailable errors."""
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.SERVICE_UNAVAILABLE,
            context=context,
            original_exception=original_exception,
            error_details=error_details
        )