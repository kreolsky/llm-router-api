# Error Handling Duplication Fix - Detailed Design Plan

## Overview

This document provides a comprehensive design plan to eliminate error handling duplication across the LLM Router codebase. The solution involves creating a centralized error handling system that will replace 38 instances of duplicated HTTPException patterns with a unified, maintainable approach.

## Current Problem Analysis

### 1. Existing Duplication Patterns

#### Pattern 1: Model Validation Errors
Found in multiple files with nearly identical structure:
```python
# src/services/chat_service/chat_service.py (lines 154-167)
if not requested_model:
    error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
    logger.error("Model not specified in request", extra={...})
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail,
    )

# src/services/embedding_service.py (lines 56-63)
if not requested_model:
    error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
    logger.error("Model not specified in request", extra={...})
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail,
    )
```

#### Pattern 2: Model Permission Errors
```python
# Repeated in multiple services
if allowed_models and requested_model not in allowed_models:
    error_detail = {"error": {"message": f"Model '{requested_model}' is not available for your account", "code": "model_not_allowed"}}
    logger.error(f"Model '{requested_model}' is not available for user {user_id}", extra={...})
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=error_detail,
    )
```

#### Pattern 3: Configuration Errors
```python
# Repeated across services
if not model_config:
    error_detail = {"error": {"message": f"Model '{requested_model}' not found in configuration", "code": "model_not_found"}}
    logger.error(f"Model '{requested_model}' not found in configuration", extra={...})
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=error_detail,
    )
```

#### Pattern 4: Provider Errors
```python
# Repeated in multiple services
if not provider_config:
    error_detail = {"error": {"message": f"Provider '{provider_name}' for model '{requested_model}' not found in configuration", "code": "provider_not_found"}}
    logger.error(f"Provider '{provider_name}' for model '{requested_model}' not found in configuration", extra={...})
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=error_detail,
    )
```

#### Pattern 5: Provider Communication Errors
```python
# Repeated across all provider classes
except httpx.HTTPStatusError as e:
    raise HTTPException(
        status_code=e.response.status_code,
        detail={"error": {"message": f"Provider error: {e.response.text}", "code": f"provider_http_error_{e.response.status_code}"}},
    )
except httpx.RequestError as e:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": {"message": f"Network error communicating with provider: {e}", "code": "provider_network_error"}},
    )
```

### 2. Impact Analysis

**Files Affected**:
- `src/services/chat_service/chat_service.py` (6 instances)
- `src/services/embedding_service.py` (5 instances)
- `src/services/transcription_service.py` (6 instances)
- `src/services/model_service.py` (3 instances)
- `src/providers/openai.py` (6 instances)
- `src/providers/ollama.py` (4 instances)
- `src/providers/anthropic.py` (3 instances)
- `src/core/auth.py` (4 instances)
- `src/api/main.py` (1 instance)

**Total Lines of Duplicated Code**: ~300 lines
**Maintenance Overhead**: High - changes require updates in multiple files
**Consistency Issues**: Medium - slight variations in error messages and formatting

## Proposed Solution Architecture

### 1. Centralized Error Handling System

#### 1.1 Core Components

```
src/core/error_handling/
├── __init__.py
├── error_handler.py          # Main error handling utility
├── error_types.py            # Error type definitions
├── error_formatter.py        # Error response formatting
└── error_logger.py           # Error logging utilities
```

#### 1.2 Design Principles

1. **Single Responsibility**: Each component has a specific error handling role
2. **Consistency**: All errors follow the same format and logging pattern
3. **Extensibility**: Easy to add new error types and handling patterns
4. **Backward Compatibility**: Existing error responses remain unchanged
5. **Performance**: Minimal overhead compared to current implementation

### 2. Detailed Component Design

#### 2.1 Error Types Definition (`src/core/error_handling/error_types.py`)

```python
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
```

#### 2.2 Error Logger (`src/core/error_handling/error_logger.py`)

```python
import logging
from typing import Dict, Any, Optional
from .error_types import ErrorType, ErrorContext

logger = logging.getLogger("nnp-llm-router")

class ErrorLogger:
    """Centralized error logging utility."""
    
    @staticmethod
    def log_error(
        error_type: ErrorType,
        context: ErrorContext,
        original_exception: Optional[Exception] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log an error with standardized format."""
        
        log_extra = context.to_log_extra()
        
        # Add error-specific information
        log_extra["error_type"] = error_type.code
        log_extra["error_code"] = error_type.code
        log_extra["http_status_code"] = error_type.status_code
        
        if additional_data:
            log_extra.update(additional_data)
        
        # Format the log message
        log_message = f"{error_type.format_message(**context.__dict__)}"
        
        # Add original exception information if provided
        if original_exception:
            log_extra["original_exception"] = str(original_exception)
            log_extra["original_exception_type"] = type(original_exception).__name__
            
            # Log with stack trace for debugging
            logger.error(
                log_message,
                extra=log_extra,
                exc_info=True
            )
        else:
            logger.error(
                log_message,
                extra=log_extra
            )
    
    @staticmethod
    def log_provider_error(
        provider_name: str,
        error_details: str,
        status_code: int,
        context: ErrorContext,
        original_exception: Optional[Exception] = None
    ):
        """Log provider-specific errors."""
        
        log_extra = context.to_log_extra()
        log_extra.update({
            "provider_name": provider_name,
            "provider_error_details": error_details,
            "provider_status_code": status_code,
            "error_type": "provider_error",
            "log_type": "error"
        })
        
        if original_exception:
            log_extra["original_exception"] = str(original_exception)
            log_extra["original_exception_type"] = type(original_exception).__name__
        
        logger.error(
            f"Provider '{provider_name}' returned error {status_code}: {error_details}",
            extra=log_extra,
            exc_info=original_exception is not None
        )
```

#### 2.3 Main Error Handler (`src/core/error_handling/error_handler.py`)

```python
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
```

### 3. Implementation Strategy

#### 3.1 Phase 1: Create Core Infrastructure (Day 1)
1. Create error handling directory structure
2. Implement `error_types.py` with all error type definitions
3. Implement `error_logger.py` with centralized logging
4. Implement `error_handler.py` with main error handling logic
5. Create comprehensive unit tests for all components

#### 3.2 Phase 2: Update Service Layer (Day 2)
1. Update `src/services/chat_service/chat_service.py`
2. Update `src/services/embedding_service.py`
3. Update `src/services/transcription_service.py`
4. Update `src/services/model_service.py`
5. Run integration tests to ensure compatibility

#### 3.3 Phase 3: Update Provider Layer (Day 3)
1. Update `src/providers/openai.py`
2. Update `src/providers/ollama.py`
3. Update `src/providers/anthropic.py`
4. Update `src/providers/base.py`
5. Test provider error handling with various scenarios

#### 3.4 Phase 4: Update API Layer (Day 4)
1. Update `src/core/auth.py`
2. Update `src/api/main.py`
3. Update `src/api/middleware.py`
4. End-to-end testing of all error scenarios

### 4. Migration Examples

#### 4.1 Before: Chat Service Error Handling

```python
# src/services/chat_service/chat_service.py (current implementation)
if not requested_model:
    error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
    logger.error(
        "Model not specified in request",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "log_type": "error",
            "detail": error_detail
        }
    )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail,
    )
```

#### 4.2 After: Chat Service Error Handling

```python
# src/services/chat_service/chat_service.py (new implementation)
from src.core.error_handling.error_handler import ErrorHandler
from src.core.error_handling.error_types import ErrorContext

# Create error context
context = ErrorContext(
    request_id=request_id,
    user_id=user_id,
    model_id=requested_model
)

# Handle error with centralized utility
raise ErrorHandler.handle_model_not_specified(context)
```

#### 4.3 Before: Provider Error Handling

```python
# src/providers/openai.py (current implementation)
except httpx.HTTPStatusError as e:
    raise HTTPException(
        status_code=e.response.status_code,
        detail={"error": {"message": f"Provider error: {e.response.text}", "code": f"provider_http_error_{e.response.status_code}"}},
    )
except httpx.RequestError as e:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": {"message": f"Network error communicating with provider: {e}", "code": "provider_network_error"}},
    )
```

#### 4.4 After: Provider Error Handling

```python
# src/providers/openai.py (new implementation)
from src.core.error_handling.error_handler import ErrorHandler
from src.core.error_handling.error_types import ErrorContext

# Create error context
context = ErrorContext(
    request_id=getattr(request.state, 'request_id', None) if 'request' in locals() else None,
    user_id=getattr(request.state, 'project_name', None) if 'request' in locals() else None,
    provider_name="openai"
)

except httpx.HTTPStatusError as e:
    raise ErrorHandler.handle_provider_http_error(
        original_exception=e,
        context=context,
        provider_name="openai"
    )
except httpx.RequestError as e:
    raise ErrorHandler.handle_provider_network_error(
        original_exception=e,
        context=context,
        provider_name="openai"
    )
```

### 5. Testing Strategy

#### 5.1 Unit Tests
```python
# tests/core/error_handling/test_error_handler.py
import pytest
from fastapi import HTTPException
from src.core.error_handling.error_handler import ErrorHandler
from src.core.error_handling.error_types import ErrorType, ErrorContext

class TestErrorHandler:
    def test_handle_model_not_specified(self):
        context = ErrorContext(request_id="test-123", user_id="test-user")
        exception = ErrorHandler.handle_model_not_specified(context)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 400
        assert exception.detail["error"]["code"] == "model_not_specified"
        assert exception.detail["error"]["message"] == "Model not specified in request"
    
    def test_handle_model_not_allowed(self):
        context = ErrorContext(request_id="test-123", user_id="test-user")
        exception = ErrorHandler.handle_model_not_allowed("gpt-4", context)
        
        assert isinstance(exception, HTTPException)
        assert exception.status_code == 403
        assert exception.detail["error"]["code"] == "model_not_allowed"
        assert "gpt-4" in exception.detail["error"]["message"]
```

#### 5.2 Integration Tests
```python
# tests/integration/test_error_handling_integration.py
import pytest
from fastapi.testclient import TestClient
from src.api.main import app

class TestErrorHandlingIntegration:
    def test_model_not_specified_error(self):
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={"messages": [{"role": "user", "content": "test"}]}
        )
        
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "model_not_specified"
    
    def test_model_not_allowed_error(self):
        client = TestClient(app)
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer restricted-key"},
            json={"model": "forbidden-model", "messages": [{"role": "user", "content": "test"}]}
        )
        
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "model_not_allowed"
```

### 6. Benefits and Metrics

#### 6.1 Code Reduction
- **Before**: ~300 lines of duplicated error handling code
- **After**: ~100 lines of centralized error handling code
- **Reduction**: 67% decrease in error handling code

#### 6.2 Maintainability Improvements
- **Single Source of Truth**: All error handling logic in one place
- **Consistent Format**: Standardized error responses across all endpoints
- **Easy Updates**: Changes to error format require updates in only one file
- **Better Testing**: Centralized error handling easier to test comprehensively

#### 6.3 Developer Experience
- **Simplified Code**: Service code focuses on business logic
- **Better Documentation**: Clear error type definitions
- **IDE Support**: Better autocomplete and type hints for error handling
- **Reduced Bugs**: Less chance for inconsistencies in error handling

### 7. Risk Mitigation

#### 7.1 Backward Compatibility
- All existing error response formats remain unchanged
- Error codes and messages stay the same
- HTTP status codes remain consistent

#### 7.2 Performance Considerations
- Minimal overhead compared to current implementation
- Lazy creation of error contexts
- Efficient logging with structured format

#### 7.3 Rollback Strategy
- Changes can be rolled back file by file if needed
- Original error handling patterns preserved in comments during transition
- Comprehensive testing before deployment

### 8. Success Criteria

#### 8.1 Functional Criteria
- [ ] All existing error scenarios continue to work
- [ ] Error response formats remain unchanged
- [ ] All HTTP status codes remain consistent
- [ ] Error logging format is consistent across all services

#### 8.2 Quality Criteria
- [ ] Code duplication reduced by at least 60%
- [ ] All error handling covered by unit tests
- [ ] Integration tests pass for all error scenarios
- [ ] Code review approves implementation

#### 8.3 Maintainability Criteria
- [ ] New error types can be added easily
- [ ] Error format changes require minimal code updates
- [ ] Documentation is clear and comprehensive
- [ ] Developer feedback is positive

## Conclusion

This design provides a comprehensive solution to eliminate error handling duplication while maintaining backward compatibility and improving maintainability. The phased implementation approach ensures minimal risk while delivering significant improvements in code quality and developer experience.

The centralized error handling system will serve as a foundation for future improvements and make the codebase more maintainable and consistent.