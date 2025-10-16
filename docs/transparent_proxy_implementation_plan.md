# Transparent Proxy Implementation Plan

## Core Principle
The router should be a simple proxy that:
1. Accepts OpenAI-compatible requests
2. Forwards them to providers
3. Returns the provider's response exactly as received
4. No transformation, no filtering, no interference

## Implementation Steps

### Step 1: Modify StreamProcessor for Complete Transparency

```python
# src/services/chat_service/stream_processor.py

class StreamProcessor:
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        # Keep existing initialization for error handling
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.buffer = ""
        self.statistics = StatisticsCollector()
        self.content_length = 0
    
    async def process_stream(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           model_id: str,
                           request_id: str,
                           user_id: str) -> AsyncGenerator[bytes, None]:
        """
        Completely transparent stream processing - just pass through everything
        """
        logger.info("Starting transparent stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id
        })
        
        try:
            # Just pass through everything from provider without any processing
            async for chunk in provider_stream:
                yield chunk
                
        except Exception as e:
            logger.error("Error in transparent stream processing", extra={
                "request_id": request_id,
                "user_id": user_id,
                "error": str(e)
            }, exc_info=True)
            
            # Still format errors properly
            yield self._format_error(e)
```

### Step 2: Simplify Chat Service for Transparent Proxying

```python
# src/services/chat_service/chat_service.py

class ChatService:
    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
        """
        Transparent chat completion - just forward requests and return responses as-is
        """
        project_name, api_key, allowed_models, _ = auth_data
        request_id = request.state.request_id
        user_id = project_name

        request_body = await request.json()
        requested_model = request_body.get("model")

        # ... existing validation logic ...

        # Get provider configuration
        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        
        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        provider_config = current_config.get("providers", {}).get(provider_name)
        
        # Get provider instance
        provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        
        try:
            # Transform request: Replace the model name with the provider's specific model name
            request_body["model"] = provider_model_name
            
            # Merge options from model_config into the request_body
            options = model_config.get("options")
            if options:
                request_body = deep_merge(request_body, options)

            # Just forward to provider and return response as-is
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            # Return response exactly as received from provider
            return response_data
            
        except Exception as e:
            # ... existing error handling ...
```

### Step 3: Update OpenAI Provider for Complete Transparency

```python
# src/providers/openai.py

class OpenAICompatibleProvider(BaseProvider):
    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # Transform request: Replace the model name with the provider's specific model name
        request_body["model"] = provider_model_name
        
        # Merge options from model_config into the request_body
        options = model_config.get("options")
        if options:
            request_body = deep_merge(request_body, options)

        # Ensure stream is handled correctly
        stream = request_body.get("stream", False)
        
        try:
            if stream:
                # For streaming, return the raw stream from provider
                return await self._stream_request(self.client, "/chat/completions", request_body)
            else:
                # For non-streaming, return the raw response from provider
                non_stream_timeout = httpx.Timeout(
                    connect=10.0,
                    read=60.0,
                    write=10.0,
                    pool=10.0
                )
                response = await self.client.post(f"{self.base_url}/chat/completions",
                                             headers=self.headers,
                                             json=request_body,
                                             timeout=non_stream_timeout)
                response.raise_for_status()
                
                # Return the raw JSON response from provider
                return response.json()
                
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

### Step 4: Simplified Configuration

```yaml
# config/providers.yaml (simplified)
providers:
  openai:
    type: openai
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
  deepseek:
    type: openai
    base_url: https://api.deepseek.com/v1
    api_key_env: DEEPSEEK_API_KEY
  ollama:
    type: ollama
    base_url: http://localhost:11434/api
```

```yaml
# config/models.yaml (unchanged)
models:
  deepseek/chat:
    provider: deepseek
    provider_model_name: deepseek-chat
  deepseek/reasoner:
    provider: deepseek
    provider_model_name: deepseek-reasoner
  # ... other models ...
```

### Step 5: Simple Test for Transparency

```python
# tests/manual/test_complete_transparency.py
async def test_complete_transparency():
    """Test that all provider responses are returned as-is"""
    
    # Test with reasoning model
    payload = {
        "model": "deepseek/reasoner",
        "messages": [{"role": "user", "content": "Solve step by step: 2+2*3"}],
        "stream": True
    }
    
    response_parts = []
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", "http://localhost:8000/v1/chat/completions",
                                json=payload, timeout=30) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line.strip() != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        # Extract ALL content from delta, not just standard fields
                        if "choices" in chunk and chunk["choices"]:
                            delta = chunk["choices"][0].get("delta", {})
                            for key, value in delta.items():
                                if isinstance(value, str) and value.strip():
                                    response_parts.append(value)
                    except json.JSONDecodeError:
                        pass
    
    full_response = "".join(response_parts)
    print(f"Full response: {full_response}")
    
    # Should contain reasoning steps, not just final answer
    assert len(full_response) > 50, "Should receive complete response including reasoning"
    assert "think" in full_response.lower() or "reason" in full_response.lower() or len(full_response) > 100
```

## Implementation Benefits

1. **Complete Transparency**: Zero transformation of provider responses
2. **Maximum Compatibility**: Works with any provider, regardless of response format
3. **Zero Overhead**: No processing delays for streaming responses
4. **Future-Proof**: Automatically supports new provider features without code changes
5. **Simplicity**: Minimal code changes, maximum reliability

## Key Changes Summary

1. **StreamProcessor**: Removed all content extraction and transformation - just pass through
2. **ChatService**: Removed response processing - just forward responses
3. **OpenAI Provider**: Returns raw responses without modification
4. **Configuration**: Simplified - no need for format specifications

## Core Principle Achieved

"The task of this project is to aggregate several providers into one point and use as a single API. It should minimally interfere with the provider's work, and all information should be transparently transmitted to the client."

This approach achieves the goal of complete transparent proxying with minimal interference in provider operations.