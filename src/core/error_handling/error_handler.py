"""Factory for creating standardized HTTPExceptions with logging."""

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
        """Create a standardized HTTPException with proper logging.

        PROVIDER_HTTP_ERROR and PROVIDER_STREAM_ERROR use dynamic status codes
        extracted from original_exception rather than a fixed value.
        """
        if context is None:
            context = ErrorContext()

        format_dict = {**context.__dict__, **format_kwargs}
        error_detail = error_type.create_error_detail(**format_dict)

        # WHY: provider errors carry the upstream status code, not a fixed one
        status_code = error_type.status_code
        if error_type in (ErrorType.PROVIDER_HTTP_ERROR, ErrorType.PROVIDER_STREAM_ERROR) and original_exception:
            if hasattr(original_exception, 'response') and hasattr(original_exception.response, 'status_code'):
                status_code = original_exception.response.status_code
            elif hasattr(original_exception, 'status_code'):
                status_code = original_exception.status_code
        error_detail["error"]["code"] = status_code

        if error_type in (ErrorType.PROVIDER_HTTP_ERROR, ErrorType.PROVIDER_STREAM_ERROR):
            metadata = error_detail["error"].setdefault("metadata", {})
            if context and context.provider_name:
                metadata["provider_name"] = context.provider_name
            if original_exception and hasattr(original_exception, 'response'):
                try:
                    metadata["raw"] = original_exception.response.text
                except Exception:
                    pass
        
        if log_error:
            additional_data = {"error_detail": error_detail}
            ErrorLogger.log_error(
                error_type=error_type,
                context=context,
                original_exception=original_exception,
                additional_data=additional_data
            )
        
        return HTTPException(
            status_code=status_code,
            detail=error_detail
        )
    
    @staticmethod
    def handle_model_not_specified(context: ErrorContext) -> HTTPException:
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.MODEL_NOT_SPECIFIED,
            context=context
        )
    
    @staticmethod
    def handle_model_not_allowed(model_id: str, context: ErrorContext) -> HTTPException:
        context.model_id = model_id
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.MODEL_NOT_ALLOWED,
            context=context
        )
    
    @staticmethod
    def handle_model_not_found(model_id: str, context: ErrorContext) -> HTTPException:
        context.model_id = model_id
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.MODEL_NOT_FOUND,
            context=context
        )
    
    @staticmethod
    def handle_provider_not_found(provider_name: str, model_id: str, context: ErrorContext) -> HTTPException:
        context.provider_name = provider_name
        context.model_id = model_id
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.PROVIDER_NOT_FOUND,
            context=context
        )
    
    @staticmethod
    def handle_provider_config_error(error_details: str, context: ErrorContext, original_exception: Optional[Exception] = None) -> HTTPException:
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
        if provider_name:
            context.provider_name = provider_name
        
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.PROVIDER_NETWORK_ERROR,
            context=context,
            original_exception=original_exception,
            error_details=str(original_exception)
        )
    
    @staticmethod
    def handle_provider_stream_error(
        error_details: str,
        context: ErrorContext,
        status_code: int = 500,
        error_code: str = "provider_stream_error",
        original_exception: Optional[Exception] = None
    ) -> HTTPException:
        if context.provider_name:
            ErrorLogger.log_provider_error(
                provider_name=context.provider_name,
                error_details=error_details,
                status_code=status_code,
                context=context,
                original_exception=original_exception
            )
        
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.PROVIDER_STREAM_ERROR,
            context=context,
            original_exception=original_exception,
            error_details=error_details,
            log_error=False  # Already logged above
        )
    
    @staticmethod
    def handle_internal_server_error(
        error_details: str,
        context: ErrorContext,
        original_exception: Optional[Exception] = None
    ) -> HTTPException:
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
        return ErrorHandler.create_http_exception(
            error_type=ErrorType.SERVICE_UNAVAILABLE,
            context=context,
            original_exception=original_exception,
            error_details=error_details
        )