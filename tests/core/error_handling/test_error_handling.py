"""
Tests for the centralized error handling system.

This test suite verifies that the new error handling system works correctly
and maintains backward compatibility with existing error responses.
"""

import pytest
from fastapi import HTTPException
import httpx

from src.core.error_handling import ErrorHandler, ErrorType, ErrorContext, ErrorLogger


class TestErrorTypes:
    """Test error type definitions and formatting."""
    
    def test_model_not_specified_error(self):
        """Test MODEL_NOT_SPECIFIED error type."""
        error_type = ErrorType.MODEL_NOT_SPECIFIED
        assert error_type.code == "model_not_specified"
        assert error_type.status_code == 400
        assert error_type.format_message() == "Model not specified in request"
    
    def test_model_not_allowed_error(self):
        """Test MODEL_NOT_ALLOWED error type with parameter."""
        error_type = ErrorType.MODEL_NOT_ALLOWED
        message = error_type.format_message(model_id="gpt-4")
        assert "gpt-4" in message
        assert message == "Model 'gpt-4' is not available for your account"
    
    def test_provider_not_found_error(self):
        """Test PROVIDER_NOT_FOUND error type with parameters."""
        error_type = ErrorType.PROVIDER_NOT_FOUND
        message = error_type.format_message(provider_name="openai", model_id="gpt-4")
        assert "openai" in message
        assert "gpt-4" in message
    
    def test_error_detail_creation(self):
        """Test error detail dictionary creation."""
        error_type = ErrorType.MODEL_NOT_FOUND
        error_detail = error_type.create_error_detail(model_id="gpt-4")
        
        assert "error" in error_detail
        assert error_detail["error"]["code"] == "model_not_found"
        assert "gpt-4" in error_detail["error"]["message"]


class TestErrorContext:
    """Test error context creation and logging."""
    
    def test_minimal_context(self):
        """Test creating minimal error context."""
        context = ErrorContext()
        assert context.request_id is None
        assert context.user_id is None
        assert context.model_id is None
        
        log_extra = context.to_log_extra()
        assert log_extra["log_type"] == "error"
        assert "request_id" not in log_extra
        assert "user_id" not in log_extra
    
    def test_full_context(self):
        """Test creating full error context."""
        context = ErrorContext(
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            endpoint_path="/v1/chat/completions",
            provider_name="openai"
        )
        
        log_extra = context.to_log_extra()
        assert log_extra["request_id"] == "req-123"
        assert log_extra["user_id"] == "user-456"
        assert log_extra["model_id"] == "gpt-4"
        assert log_extra["endpoint_path"] == "/v1/chat/completions"
        assert log_extra["provider_name"] == "openai"
    
    def test_context_with_additional_data(self):
        """Test context with additional context data."""
        context = ErrorContext(
            request_id="req-123",
            custom_field="custom_value"
        )
        
        log_extra = context.to_log_extra()
        assert log_extra["custom_field"] == "custom_value"


class TestErrorHandler:
    """Test main error handler functionality."""
    
    def test_handle_model_not_specified(self):
        """Test handling model not specified error."""
        context = ErrorContext(request_id="req-123", user_id="user-456")
        exception = ErrorHandler.handle_model_not_specified(context)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 400
        assert exception.detail["error"]["code"] == "model_not_specified"
        assert exception.detail["error"]["message"] == "Model not specified in request"
    
    def test_handle_model_not_allowed(self):
        """Test handling model not allowed error."""
        context = ErrorContext(request_id="req-123", user_id="user-456")
        exception = ErrorHandler.handle_model_not_allowed("gpt-4", context)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 403
        assert exception.detail["error"]["code"] == "model_not_allowed"
        assert "gpt-4" in exception.detail["error"]["message"]
    
    def test_handle_model_not_found(self):
        """Test handling model not found error."""
        context = ErrorContext(request_id="req-123", user_id="user-456")
        exception = ErrorHandler.handle_model_not_found("gpt-4", context)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 404
        assert exception.detail["error"]["code"] == "model_not_found"
        assert "gpt-4" in exception.detail["error"]["message"]
    
    def test_handle_provider_not_found(self):
        """Test handling provider not found error."""
        context = ErrorContext(request_id="req-123", user_id="user-456")
        exception = ErrorHandler.handle_provider_not_found("openai", "gpt-4", context)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 404
        assert exception.detail["error"]["code"] == "provider_not_found"
        assert "openai" in exception.detail["error"]["message"]
        assert "gpt-4" in exception.detail["error"]["message"]
    
    def test_handle_provider_config_error(self):
        """Test handling provider configuration error."""
        context = ErrorContext(request_id="req-123", user_id="user-456")
        original_exception = ValueError("Invalid configuration")
        exception = ErrorHandler.handle_provider_config_error("Invalid API key", context, original_exception)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 500
        assert exception.detail["error"]["code"] == "provider_config_error"
        assert "Invalid API key" in exception.detail["error"]["message"]
    
    def test_handle_provider_http_error(self):
        """Test handling provider HTTP error."""
        context = ErrorContext(provider_name="openai")
        
        # Create a mock HTTPStatusError
        mock_response = type('MockResponse', (), {
            'status_code': 429,
            'text': 'Rate limit exceeded'
        })()
        
        original_exception = type('MockHTTPStatusError', (), {
            'response': mock_response
        })()
        
        exception = ErrorHandler.handle_provider_http_error(original_exception, context, "openai")
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 429
        assert exception.detail["error"]["code"] == "provider_http_error_429"
    
    def test_handle_provider_network_error(self):
        """Test handling provider network error."""
        context = ErrorContext(provider_name="openai")
        original_exception = httpx.RequestError("Connection timeout")
        
        exception = ErrorHandler.handle_provider_network_error(original_exception, context, "openai")
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 500
        assert exception.detail["error"]["code"] == "provider_network_error"
        assert "Connection timeout" in exception.detail["error"]["message"]
    
    def test_handle_internal_server_error(self):
        """Test handling internal server error."""
        context = ErrorContext(request_id="req-123", user_id="user-456")
        original_exception = ValueError("Something went wrong")
        
        exception = ErrorHandler.handle_internal_server_error("Database error", context, original_exception)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 500
        assert exception.detail["error"]["code"] == "internal_server_error"
        assert "Database error" in exception.detail["error"]["message"]
    
    def test_handle_auth_errors(self):
        """Test handling authentication errors."""
        context = ErrorContext()
        
        # Test missing API key
        exception = ErrorHandler.handle_auth_errors("missing_api_key", context)
        assert exception.status_code == 401
        assert exception.detail["error"]["code"] == "missing_api_key"
        
        # Test invalid API key
        exception = ErrorHandler.handle_auth_errors("invalid_api_key", context)
        assert exception.status_code == 401
        assert exception.detail["error"]["code"] == "invalid_api_key"
    
    def test_handle_endpoint_not_allowed(self):
        """Test handling endpoint not allowed error."""
        context = ErrorContext(user_id="user-456")
        exception = ErrorHandler.handle_endpoint_not_allowed("/v1/admin", context)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 403
        assert exception.detail["error"]["code"] == "endpoint_not_allowed"
        assert "/v1/admin" in exception.detail["error"]["message"]
    
    def test_handle_service_unavailable(self):
        """Test handling service unavailable error."""
        context = ErrorContext(provider_name="transcriber")
        original_exception = ConnectionError("Service down")
        
        exception = ErrorHandler.handle_service_unavailable("Service down", context, original_exception)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 503
        assert exception.detail["error"]["code"] == "service_unavailable"
        assert "Service down" in exception.detail["error"]["message"]


class TestBackwardCompatibility:
    """Test that new error handling maintains backward compatibility."""
    
    def test_model_not_specified_response_format(self):
        """Test that model not specified error response format is unchanged."""
        context = ErrorContext(request_id="req-123")
        exception = ErrorHandler.handle_model_not_specified(context)
        
        # Verify response format matches expected structure
        assert "error" in exception.detail
        assert "message" in exception.detail["error"]
        assert "code" in exception.detail["error"]
        assert exception.detail["error"]["code"] == "model_not_specified"
        assert exception.detail["error"]["message"] == "Model not specified in request"
        assert exception.status_code == 400
    
    def test_model_not_allowed_response_format(self):
        """Test that model not allowed error response format is unchanged."""
        context = ErrorContext(request_id="req-123")
        exception = ErrorHandler.handle_model_not_allowed("gpt-4", context)
        
        # Verify response format matches expected structure
        assert "error" in exception.detail
        assert "message" in exception.detail["error"]
        assert "code" in exception.detail["error"]
        assert exception.detail["error"]["code"] == "model_not_allowed"
        assert "gpt-4" in exception.detail["error"]["message"]
        assert exception.status_code == 403
    
    def test_provider_error_response_format(self):
        """Test that provider error response format is unchanged."""
        context = ErrorContext(provider_name="openai")
        original_exception = httpx.RequestError("Connection failed")
        
        exception = ErrorHandler.handle_provider_network_error(original_exception, context, "openai")
        
        # Verify response format matches expected structure
        assert "error" in exception.detail
        assert "message" in exception.detail["error"]
        assert "code" in exception.detail["error"]
        assert exception.detail["error"]["code"] == "provider_network_error"
        assert "Connection failed" in exception.detail["error"]["message"]
        assert exception.status_code == 500


class TestIntegration:
    """Integration tests for the error handling system."""
    
    def test_error_context_propagation(self):
        """Test that error context is properly propagated through the system."""
        context = ErrorContext(
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            provider_name="openai"
        )
        
        exception = ErrorHandler.handle_model_not_found("gpt-4", context)
        
        # Verify context information is preserved
        assert exception.status_code == 404
        assert exception.detail["error"]["code"] == "model_not_found"
    
    def test_multiple_error_types(self):
        """Test handling multiple different error types."""
        context = ErrorContext(request_id="req-123", user_id="user-456")
        
        # Test different error types
        errors = [
            ErrorHandler.handle_model_not_specified(context),
            ErrorHandler.handle_model_not_allowed("gpt-4", context),
            ErrorHandler.handle_model_not_found("gpt-4", context),
            ErrorHandler.handle_internal_server_error("Test error", context)
        ]
        
        # Verify all errors are HTTPExceptions with correct status codes
        status_codes = [e.status_code for e in errors]
        assert status_codes == [400, 403, 404, 500]
        
        # Verify all errors have correct format
        for error in errors:
            assert "error" in error.detail
            assert "message" in error.detail["error"]
            assert "code" in error.detail["error"]


if __name__ == "__main__":
    pytest.main([__file__])