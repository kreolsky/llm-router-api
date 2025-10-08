# OpenRouter Streaming Error Analysis

## Executive Summary

This report analyzes a 400 Bad Request error occurring with OpenRouter provider during streaming requests. The error was captured in debug logs and is caused by **client-side SSE parsing results being incorrectly added to conversation messages** that are sent back to the provider.

## Error Details

### Error Message
```
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://openrouter.ai/api/v1/chat/completions'
```

### Error Traceback
The error occurs in the streaming flow:
1. [`src/services/chat_service/stream_processor.py:118`](src/services/chat_service/stream_processor.py:118) - Processing provider stream
2. [`src/providers/base.py:129`](src/providers/base.py:129) - Calling `response.raise_for_status()`
3. [`src/providers/base.py:160`](src/providers/base.py:160) - Raising `ProviderStreamError`

### Request Information
- **Model**: `gemini/mini` (mapped to `google/gemini-2.0-flash-001`)
- **Streaming**: Enabled
- **Request ID**: `1112160b572811d9`
- **User**: `dead-internet`
- **Timestamp**: 2025-10-08T15:38:57+0000

## Root Cause Analysis

### 1. Client-Side SSE Contamination Issue

**CRITICAL DISCOVERY**: The debug logs reveal that the `done: true` field is NOT coming from the server-side code, but from **client-side SSE parsing results being incorrectly added back to conversation messages**:

```json
{
  "role": "assistant",
  "content": "<status title=\"Edited\" done=\"true\" />",
  "done": true
}
```

**Root Cause Analysis**:
1. **Server-side SSE parsing**: In [`src/services/chat_service/stream_processor.py:312-313`](src/services/chat_service/stream_processor.py:312-313), the server correctly parses `[DONE]` events and returns `{'done': True}` for internal processing
2. **Client-side contamination**: The client application is incorrectly taking these SSE parsing results and adding them back into the conversation history
3. **Round-trip pollution**: When the client sends the next request, it includes the contaminated messages with `done: true` fields
4. **Provider rejection**: OpenRouter strictly validates the message format and rejects requests with non-standard fields

**Evidence from Debug Logs**:
- The `done: true` appears in messages sent TO OpenRouter (lines 4-8 in debug.log)
- This field is only created server-side during SSE parsing (line 313 in stream_processor.py)
- The field should NEVER be sent back to any provider

**Other Issues Identified**:
1. **Empty assistant content**: There's an assistant message with empty content (`"content": ""`)
2. **Mixed language content**: The conversation includes Russian text which might be causing encoding issues

### 2. Request Flow Analysis

The request follows this path:
1. Client sends request to `/v1/chat/completions`
2. [`src/services/chat_service/chat_service.py`](src/services/chat_service/chat_service.py) processes the request
3. Model configuration maps `gemini/mini` to `google/gemini-2.0-flash-001`
4. [`src/providers/openai.py`](src/providers/openai.py) formats the request for OpenRouter
5. [`src/providers/base.py`](src/providers/base.py) handles the streaming request
6. Error occurs when OpenRouter returns 400 status

### 3. Provider Comparison Analysis

**Important Observation**: The same message format with non-standard `done` fields works fine with other providers but fails with OpenRouter. This indicates different validation approaches:

**Providers that ignore non-standard fields** (based on configuration):
- **DeepSeek** (`deepseek/chat`, `deepseek/reasoner`) - Uses `https://api.deepseek.com/v1`
- **ZAI** (`glm/air`, `glm/chat`) - Uses `https://api.z.ai/api/paas/v4`
- **Local providers** (`orange`, `box`) - More lenient validation

**OpenRouter-specific behavior**:
- **Stricter validation**: OpenRouter validates message format more strictly than other providers
- **Rejects unknown fields**: Unlike other providers that simply ignore unknown fields, OpenRouter rejects requests with non-standard fields
- **Streaming-specific issue**: The error occurs specifically with streaming requests, suggesting different validation for streaming vs non-streaming endpoints

From the configuration in [`config/providers.yaml`](config/providers.yaml:22-29):
```yaml
openrouter:
  type: openai
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
  stream_format: sse
  headers:
    HTTP-Referer: "https://nnp.space"
    X-Title: "nnp.space"
```

All providers are configured as `type: openai` but implement different validation strategies.

## Proposed Solutions

### Solution 1: Server-Side Message Sanitization (Immediate Fix)

Implement message sanitization in [`src/providers/openai.py`](src/providers/openai.py) to remove client-side contamination before sending to any provider:

```python
def _sanitize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitize messages to remove non-standard fields from client-side contamination"""
    sanitized = []
    for message in messages:
        # Only keep standard OpenAI API fields
        clean_message = {
            "role": message.get("role"),
            "content": message.get("content")
        }
        # Add name if present (optional standard field)
        if "name" in message:
            clean_message["name"] = message["name"]
        
        sanitized.append(clean_message)
    return sanitized
```

### Solution 2: Fix SSE Event Handling (Root Cause Fix)

Modify the SSE parsing in [`src/services/chat_service/stream_processor.py`](src/services/chat_service/stream_processor.py) to avoid creating `{'done': True}` objects that could be misinterpreted:

```python
def _parse_sse_event(self, event_raw: str) -> Optional[Dict[str, Any]]:
    """Parse SSE event without creating ambiguous 'done' objects"""
    if not event_raw.strip():
        return None
    
    try:
        for line in event_raw.split('\n'):
            line = line.strip()
            
            # Пропускаем комментарии
            if line.startswith(':'):
                continue
            
            if line.startswith('data: '):
                data_part = line[6:].strip()
                
                # [DONE] - return a special marker that won't be confused with message fields
                if data_part == '[DONE]':
                    return {'__stream_end__': True}  # Use special internal marker
                
                # Парсим JSON
                try:
                    return json.loads(data_part)
                except json.JSONDecodeError:
                    return None
        
        return None
    except Exception as e:
        logger.error(f"Error parsing SSE event: {e}", exc_info=True)
        return None
```

And update the processing logic to handle the new marker:

```python
async def _process_event_data(self, event_data: Dict[str, Any], model_id: str, request_id: str, full_content: str) -> Optional[bytes]:
    """Process event data with improved stream end handling"""
    if not event_data:
        return None
    
    # Handle stream end with special marker
    if event_data.get('__stream_end__'):
        return None
    
    # Rest of the existing logic...
```

```python
def _sanitize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitize messages to remove non-standard fields"""
    sanitized = []
    for message in messages:
        # Only keep standard OpenAI API fields
        clean_message = {
            "role": message.get("role"),
            "content": message.get("content")
        }
        # Add name if present (optional standard field)
        if "name" in message:
            clean_message["name"] = message["name"]
        
        sanitized.append(clean_message)
    return sanitized
```

### Solution 3: Enhanced Error Handling

Improve error handling in [`src/providers/base.py`](src/providers/base.py) to capture more detailed error information from OpenRouter:

```python
# In the _stream_request method, enhance error parsing
try:
    response_text = e.response.text
except httpx.ResponseNotRead:
    response_text = "Unable to read error response from provider"

# Try to extract more detailed error information
try:
    error_json = e.response.json()
    if "error" in error_json:
        logger.error(f"Provider error details: {error_json['error']}")
except:
    pass
```

### Solution 4: Message Validation

Add validation in [`src/services/chat_service/chat_service.py`](src/services/chat_service/chat_service.py) to validate messages before processing:

```python
def _validate_messages(self, messages: List[Dict[str, Any]]) -> bool:
    """Validate message format before sending to provider"""
    required_fields = ["role", "content"]
    
    for message in messages:
        for field in required_fields:
            if field not in message:
                return False
        # Check role validity
        if message["role"] not in ["system", "user", "assistant"]:
            return False
        # Check content is not empty for non-last assistant messages
        if message["role"] == "assistant" and not message.get("content"):
            return False
    
    return True
```

### Solution 5: Client-Side Fix (Recommended Long-term)

The best long-term solution is to fix the client-side application to not add SSE parsing results back to conversation messages. This would involve:

1. **Client-side message filtering**: Ensure the client only adds actual message content to conversation history
2. **Separate SSE handling**: Handle streaming events separately from message state management
3. **Message validation**: Validate messages on the client side before sending to server

### Solution 6: Provider-Specific Message Handling

Implement provider-specific message handling based on provider validation strictness:

```yaml
# In config/providers.yaml
openrouter:
  type: openai
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
  stream_format: sse
  strict_validation: true  # Flag for strict validation
  headers:
    HTTP-Referer: "https://nnp.space"
    X-Title: "nnp.space"
```

Then in the provider code, check this flag and apply sanitization only for providers with strict validation.

## Implementation Priority

1. **Critical Priority**: Implement Solution 1 (Server-Side Message Sanitization) - Immediate fix to prevent client-side contamination from breaking requests
2. **High Priority**: Implement Solution 2 (Fix SSE Event Handling) - Prevents creation of ambiguous `{'done': True}` objects that could be misinterpreted
3. **Medium Priority**: Implement Solution 3 (Enhanced Error Handling) - This will improve debugging for future issues
4. **Low Priority**: Implement Solution 4 (Message Validation) - This provides early detection of issues
5. **Recommended**: Solution 5 (Client-Side Fix) - The proper long-term solution to fix the root cause
6. **Future Enhancement**: Solution 6 (Provider-Specific Message Handling) - For fine-tuning provider behavior based on validation strictness

## Testing Recommendations

1. Create test cases with various message formats including:
   - Messages with non-standard fields
   - Empty assistant messages
   - Mixed language content
2. Test streaming specifically with problematic message sequences
3. Verify that message sanitization doesn't break functionality with other providers

## Conclusion

The issue is caused by **client-side SSE contamination** where streaming event parsing results are being incorrectly added back to conversation messages and sent to providers. While most providers (DeepSeek, ZAI, local providers) ignore non-standard fields like `done: true`, OpenRouter has stricter validation and rejects these contaminated requests.

**Key Findings**:
1. The `{'done': True}` objects are created server-side during SSE parsing for internal processing
2. The client incorrectly adds these objects back to conversation history
3. OpenRouter strictly validates message format and rejects requests with non-standard fields
4. Other providers are more lenient and simply ignore unknown fields

**Recommended Approach**:
1. **Immediate fix**: Server-side message sanitization to protect against client-side contamination
2. **Long-term fix**: Fix the client-side application to properly separate SSE handling from message state management
3. **Prevention**: Modify SSE event handling to use less ambiguous internal markers

## Additional Notes

- The error is intermittent because it depends on when the client sends contaminated messages
- The issue only affects streaming requests where SSE events with `{'done': True}` are generated
- Different providers implement different validation strategies despite all being "OpenAI-compatible"
- The debug logging implementation was crucial in identifying this client-side contamination issue
- This is a classic example of client-server state management boundary violations
- The `{'done': True}` objects should never leave the server-side streaming processing context