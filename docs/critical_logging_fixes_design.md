# Critical Logging Fixes Design Document

## Overview

This document outlines the design and implementation plan for addressing the critical logging inconsistencies identified in the logging audit. These fixes are essential for maintaining consistent, reliable, and debuggable logging across the application.

## Critical Issues to Address

1. **Standardize all logging imports to use the centralized logging module**
2. **Replace all direct logger calls with centralized utilities**
3. **Ensure all error logs include stack traces**
4. **Remove all print statements from production code**

## Implementation Plan

### Phase 1: Centralize Logging Imports

#### 1.1 Update Core Logging Module (`src/core/logging/__init__.py`)

**Current Issues:**
- Multiple logger instances (logger vs std_logger)
- Confusing export structure
- No clear guidance on which logger to use

**Proposed Changes:**
```python
"""
Centralized logging infrastructure for the LLM Router.

This module provides a single point of access to all logging functionality,
ensuring consistent logging patterns across the application.
"""

# Import the main configured logger instance
from .config import setup_logging, logger as _base_logger

# Import centralized utilities
from .utils import RequestLogger, DebugLogger, PerformanceLogger, StreamingLogger
from .logger import Logger as LoggerClass

# Create a single, unified logger instance
app_logger = LoggerClass(_base_logger)

# Export only the necessary components
__all__ = [
    'logger',           # Main application logger (replaces both logger and std_logger)
    'setup_logging',    # Logging configuration function
    'RequestLogger',    # Request/response logging utility
    'DebugLogger',      # Debug logging utility
    'PerformanceLogger',# Performance logging utility
    'StreamingLogger',  # Streaming response logging utility
    'LoggerClass'       # Logger class for advanced usage
]

# Backward compatibility aliases (to be deprecated)
logger = app_logger
std_logger = _base_logger
```

#### 1.2 Update Import Patterns Across All Files

**Files to Update:**
- `src/api/main.py`
- `src/providers/openai.py`
- `src/providers/anthropic.py`
- `src/providers/ollama.py`
- `src/services/transcription_service.py`
- `src/services/embedding_service.py`
- `src/api/middleware.py`
- `src/services/chat_service/chat_service.py`
- `src/core/sanitizer.py`
- `src/providers/base.py`

**Standard Import Pattern:**
```python
# Replace all variations with this single import
from ..core.logging import (
    logger,
    RequestLogger,
    DebugLogger,
    PerformanceLogger,
    StreamingLogger
)
```

### Phase 2: Replace Direct Logger Calls with Centralized Utilities

#### 2.1 Create Standardized Logging Patterns

**Request/Response Logging Pattern:**
```python
# Before
logger.info(f"User {user_id} requesting transcription for model {model_id}")

# After
RequestLogger.log_request(
    logger=logger,
    operation="Transcription Request",
    request_id=request_id,
    user_id=user_id,
    model_id=model_id,
    request_data=request_data
)
```

**Debug Logging Pattern:**
```python
# Before
logger.debug(f"DEBUG: Request JSON: {request_data}")

# After
DebugLogger.log_data_flow(
    logger=logger,
    title="DEBUG: Request JSON",
    data=request_data,
    data_flow="incoming",
    component="service_name",
    request_id=request_id
)
```

**Error Logging Pattern:**
```python
# Before
logger.error(f"Error occurred: {error_message}")

# After
logger.error(
    "Error description",
    extra={
        "error_message": error_message,
        "error_code": error_code,
        "request_id": request_id,
        "user_id": user_id
    },
    exc_info=True
)
```

#### 2.2 Specific File Updates

**`src/api/main.py` Changes:**
```python
# Before (lines 97-99)
logger.info(f"Transcription request received from {request.client.host}")
logger.info(f"Request Headers: {dict(request.headers)}")
logger.info(f"Form Fields: model={model}, response_format={response_format}, temperature={temperature}, language={language}, return_timestamps={return_timestamps}")

# After
RequestLogger.log_request(
    logger=logger,
    operation="Transcription Request",
    request_id=request.state.request_id,
    user_id=request.state.project_name,
    request_data={
        "model": model,
        "response_format": response_format,
        "temperature": temperature,
        "language": language,
        "return_timestamps": return_timestamps,
        "client_host": request.client.host,
        "headers": dict(request.headers)
    }
)
```

**`src/services/transcription_service.py` Changes:**
```python
# Before (line 49)
logger.info(f"User {user_id} requesting transcription for model {model_id}")

# After
RequestLogger.log_request(
    logger=logger,
    operation="Transcription Processing",
    request_id=request_id,
    user_id=user_id,
    model_id=model_id
)
```

**`src/core/sanitizer.py` Changes:**
```python
# Before (lines 34-59)
if not enabled:
    logger.debug("Message sanitization is disabled")
    return messages

logger.debug(f"Sanitizing {len(messages)} messages from client-side contamination")
# ... more direct logger calls

# After
if not enabled:
    logger.debug("Message sanitization is disabled", extra={
        "sanitization": {"enabled": False}
    })
    return messages

logger.debug("Sanitizing messages from client-side contamination", extra={
    "sanitization": {
        "enabled": True,
        "message_count": len(messages)
    }
})
```

### Phase 3: Ensure All Error Logs Include Stack Traces

#### 3.1 Update Error Logging Pattern

**Standard Error Logging Template:**
```python
# All error logs MUST include:
# 1. Clear error message
# 2. Structured extra data
# 3. Stack trace (exc_info=True)

logger.error(
    "Descriptive error message",
    extra={
        "error_code": "SPECIFIC_ERROR_CODE",
        "error_message": detailed_error_message,
        "request_id": request_id,
        "user_id": user_id,
        "component": "component_name",
        "operation": "operation_name"
    },
    exc_info=True
)
```

#### 3.2 Update Error Handling Locations

**`src/api/middleware.py` Updates:**
```python
# Before (lines 64-68)
std_logger.error(
    "Request processing failed with HTTPException",
    extra=error_extra_data,
    exc_info=True # Include stack trace for debugging
)

# After (already correct, just ensure consistency)
logger.error(
    "Request processing failed with HTTPException",
    extra={
        "error_type": "HTTPException",
        "request_id": request_id,
        "user_id": user_id,
        "error_message": e.detail.get("error", {}).get("message", str(e.detail)),
        "error_code": e.detail.get("error", {}).get("code", "unknown_error"),
        "http_status_code": e.status_code
    },
    exc_info=True
)
```

**`src/services/model_service.py` Updates:**
```python
# Before (lines 78-82)
except httpx.HTTPStatusError as e:
    logger.error(f"HTTP error fetching model details from provider {provider_name}: {e.response.status_code} - {e.response.text}", extra={"error_message": e.response.text, "error_code": f"provider_http_error_{e.response.status_code}"}, exc_info=True)
except httpx.RequestError as e:
    logger.error(f"Network error fetching model details from provider {provider_name}: {e}", extra={"error_message": str(e), "error_code": "provider_network_error"}, exc_info=True)
except Exception as e:
    logger.error(f"Unexpected error fetching model details from provider {provider_name}: {e}", extra={"error_message": str(e), "error_code": "unexpected_error"}, exc_info=True)

# After (standardized format)
except httpx.HTTPStatusError as e:
    logger.error(
        "HTTP error fetching model details from provider",
        extra={
            "error_type": "HTTPStatusError",
            "provider_name": provider_name,
            "http_status_code": e.response.status_code,
            "response_text": e.response.text,
            "error_code": f"provider_http_error_{e.response.status_code}",
            "operation": "fetch_model_details"
        },
        exc_info=True
    )
except httpx.RequestError as e:
    logger.error(
        "Network error fetching model details from provider",
        extra={
            "error_type": "RequestError",
            "provider_name": provider_name,
            "error_message": str(e),
            "error_code": "provider_network_error",
            "operation": "fetch_model_details"
        },
        exc_info=True
    )
except Exception as e:
    logger.error(
        "Unexpected error fetching model details from provider",
        extra={
            "error_type": "UnexpectedError",
            "provider_name": provider_name,
            "error_message": str(e),
            "error_code": "unexpected_error",
            "operation": "fetch_model_details"
        },
        exc_info=True
    )
```

### Phase 4: Remove All Print Statements

#### 4.1 Identify and Replace Print Statements

**Files with Print Statements:**
- `src/core/config_manager.py`
- `tools/generate_keys.py`

**`src/core/config_manager.py` Changes:**
```python
# Before (line 34)
print(f"Error parsing YAML file: {e}")

# After
logger.error(
    "Error parsing YAML configuration file",
    extra={
        "error_type": "YAMLParseError",
        "error_message": str(e),
        "operation": "load_config"
    },
    exc_info=True
)

# Before (line 105)
print("Initial config:", config_manager.get_config())

# After
logger.info("Configuration manager initialized", extra={
    "operation": "config_init",
    "config_keys": list(config_manager.get_config().keys())
})
```

**`tools/generate_keys.py` Changes:**
```python
# Before (lines 12-15)
print(f"Generating {num_keys} OpenRouter-like keys:")
for i in range(num_keys):
    key = generate_openrouter_key()
    print(f"Key {i+1}: {key}")

# After
logger.info("Generating API keys", extra={
    "operation": "generate_keys",
    "key_count": num_keys
})

for i in range(num_keys):
    key = generate_openrouter_key()
    logger.info("Generated API key", extra={
        "operation": "key_generated",
        "key_index": i + 1,
        "key_prefix": key[:8] + "..."  # Log only prefix for security
    })
    print(f"Key {i+1}: {key}")  # Keep print for CLI tool output
```

## Implementation Checklist

### Phase 1: Import Standardization
- [ ] Update `src/core/logging/__init__.py` with unified exports
- [ ] Update imports in `src/api/main.py`
- [ ] Update imports in `src/providers/openai.py`
- [ ] Update imports in `src/providers/anthropic.py`
- [ ] Update imports in `src/providers/ollama.py`
- [ ] Update imports in `src/services/transcription_service.py`
- [ ] Update imports in `src/services/embedding_service.py`
- [ ] Update imports in `src/api/middleware.py`
- [ ] Update imports in `src/services/chat_service/chat_service.py`
- [ ] Update imports in `src/core/sanitizer.py`
- [ ] Update imports in `src/providers/base.py`

### Phase 2: Replace Direct Logger Calls
- [ ] Update `src/api/main.py` transcription logging
- [ ] Update `src/services/transcription_service.py` request logging
- [ ] Update `src/core/sanitizer.py` debug logging
- [ ] Update all other direct logger calls with appropriate utilities

### Phase 3: Standardize Error Logging
- [ ] Update `src/api/middleware.py` error logging
- [ ] Update `src/services/model_service.py` error logging
- [ ] Update error logging in all provider files
- [ ] Update error logging in all service files
- [ ] Verify all error logs include exc_info=True

### Phase 4: Remove Print Statements
- [ ] Replace print in `src/core/config_manager.py`
- [ ] Replace print in `tools/generate_keys.py`
- [ ] Search for any remaining print statements in production code
- [ ] Add linting rule to prevent future print statements

## Testing Strategy

### Unit Tests
1. Verify all imports work correctly after changes
2. Test that centralized utilities produce expected log formats
3. Verify error logs include stack traces
4. Test that no print statements remain in production code

### Integration Tests
1. Run full application with new logging patterns
2. Verify log output consistency across all components
3. Test error scenarios to ensure proper error logging
4. Verify performance is not impacted

### Regression Tests
1. Ensure all existing functionality continues to work
2. Verify log formats remain compatible with log analysis tools
3. Test that no logging information is lost

## Rollback Plan

If issues arise during implementation:

1. **Immediate Rollback**: Revert to previous logging imports and patterns
2. **Partial Rollback**: Keep import changes but revert specific utility usage
3. **Gradual Rollback**: Disable specific logging changes while keeping others

## Success Criteria

1. All logging imports use the centralized module
2. No direct logger calls remain (all use utilities)
3. All error logs include stack traces
4. No print statements in production code
5. Log output is consistent across all components
6. No performance degradation
7. All tests pass

## Future Considerations

1. **Monitoring**: Add metrics to track logging patterns
2. **Automation**: Create linting rules to enforce logging standards
3. **Documentation**: Update developer documentation with logging guidelines
4. **Training**: Provide training to team on new logging patterns