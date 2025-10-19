# Simplified Error Handling Consolidation Plan

## Executive Summary

This plan consolidates error handling by standardizing on the `error_handling` module and removing `exceptions.py`. The approach focuses on maximum simplicity with no backward compatibility concerns.

## Current State

- `exceptions.py`: 3 custom exceptions with immediate logging
- `error_handling/`: Comprehensive error handling module with ErrorHandler, ErrorLogger, ErrorType enum, and ErrorContext
- Both approaches are used interchangeably across the codebase

## Decision

Standardize on the `error_handling` module and completely remove `exceptions.py`.

## Implementation Steps

### Step 1: Enhance error_handling Module

#### 1.1 Add Streaming Error Support

Add to `error_types.py`:
```python
class ErrorType(Enum):
    # ... existing types ...
    PROVIDER_STREAM_ERROR = ("provider_stream_error", None, "Provider streaming error: {error_details}")
```

#### 1.2 Add Immediate Logging to ErrorHandler

Enhance `error_handler.py` with immediate logging:
```python
@staticmethod
def handle_provider_stream_error(
    error_details: str,
    context: ErrorContext,
    status_code: int = 500,
    error_code: str = "provider_stream_error",
    original_exception: Optional[Exception] = None
) -> HTTPException:
    """Handle provider streaming errors with immediate logging."""
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
```

### Step 2: Replace exceptions.py Usage

#### 2.1 Update providers/base.py

Replace:
```python
# OLD
from ..core.exceptions import ProviderAPIError, ProviderNetworkError, ProviderStreamError

# In _stream_request method:
raise ProviderStreamError(
    message=error_message,
    status_code=e.response.status_code,
    error_code=error_code,
    original_exception=e
) from e

raise ProviderNetworkError(
    message=f"Network or connection error to provider: {e}",
    original_exception=e
) from e
```

With:
```python
# NEW
from ..core.error_handling import ErrorHandler, ErrorContext

# In _stream_request method:
context = ErrorContext(
    provider_name="unknown",  # Will be set by specific provider
    request_id=request_body.get("request_id")
)
raise ErrorHandler.handle_provider_stream_error(
    error_details=error_message,
    context=context,
    status_code=e.response.status_code,
    error_code=error_code,
    original_exception=e
)

raise ErrorHandler.handle_provider_network_error(
    original_exception=e,
    context=context
)
```

#### 2.2 Update stream_processor.py

Replace:
```python
# OLD
from ...core.exceptions import ProviderStreamError, ProviderNetworkError

def _format_error(self, error: Exception) -> bytes:
    if isinstance(error, ProviderStreamError):
        message = error.message
        code = error.error_code
    elif isinstance(error, ProviderNetworkError):
        message = error.message
        code = "provider_network_error"
```

With:
```python
# NEW
from fastapi import HTTPException

def _format_error(self, error: Exception) -> bytes:
    if isinstance(error, HTTPException) and hasattr(error.detail, 'get'):
        error_detail = error.detail
        if "error" in error_detail:
            error_info = error_detail["error"]
            message = error_info.get("message", str(error))
            code = error_info.get("code", "unknown_error")
        else:
            message = str(error)
            code = "http_error"
    else:
        message = f"An unexpected error occurred during streaming: {error}"
        code = "unexpected_streaming_error"
```

#### 2.3 Update Provider Implementations

For each provider (openai.py, anthropic.py, ollama.py):

Replace:
```python
# OLD
except httpx.HTTPStatusError as e:
    context = ErrorContext(provider_name="provider_name")
    raise ErrorHandler.handle_provider_http_error(e, context, "provider_name")
except httpx.RequestError as e:
    context = ErrorContext(provider_name="provider_name")
    raise ErrorHandler.handle_provider_network_error(e, context, "provider_name")
```

With:
```python
# NEW (no changes needed - already using ErrorHandler)
```

### Step 3: Remove exceptions.py

1. Delete `src/core/exceptions.py`
2. Remove all imports of the custom exceptions
3. Update any remaining references

### Step 4: Update Retry Decorator

Update `providers/base.py` retry decorator:

Replace:
```python
# OLD
except ProviderStreamError as e:
    if e.status_code == 429 and attempt < max_retries:
        # ... retry logic
```

With:
```python
# NEW
except HTTPException as e:
    if e.status_code == 429 and attempt < max_retries:
        # ... retry logic
```

## Files to Modify

1. `src/core/error_handling/error_types.py` - Add PROVIDER_STREAM_ERROR
2. `src/core/error_handling/error_handler.py` - Add handle_provider_stream_error method
3. `src/providers/base.py` - Replace exceptions with ErrorHandler calls
4. `src/services/chat_service/stream_processor.py` - Update error formatting
5. Delete `src/core/exceptions.py`

## Testing

1. Verify all error scenarios still work
2. Test streaming error handling specifically
3. Confirm immediate logging is working
4. Check that error responses maintain the same format

## Benefits

1. **Single error handling approach** - No confusion about which to use
2. **Simplified codebase** - Less duplication
3. **Better context tracking** - ErrorContext provides more information
4. **Consistent error responses** - All errors go through ErrorHandler
5. **Immediate logging preserved** - Critical for debugging streaming issues

## Timeline

1. Day 1: Enhance error_handling module
2. Day 2: Update providers and stream processor
3. Day 3: Remove exceptions.py and clean up
4. Day 4: Testing and verification

This approach maximizes simplicity by completely removing the old system and standardizing on the more comprehensive error_handling module.