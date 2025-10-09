"""
Chat completion tests for NNP LLM Router API.
Tests both streaming and non-streaming responses for all test models.
"""

import pytest
import httpx
import json
import time
import asyncio
from tests.test_utils import (
    TestTimer, StreamingResponseParser, ResponseValidator,
    TestDataGenerator, calculate_ttft_metrics, assert_performance_thresholds
)


class TestChatCompletions:
    """Test chat completion functionality."""
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_key", ["local_orange", "gemini_mini", "deepseek_chat"])
    async def test_non_streaming_chat_completion(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        model_key: str,
        sample_messages: list,
        expected_chat_response_structure: list,
        http_client: httpx.AsyncClient,
        performance_thresholds: dict
    ):
        """Test non-streaming chat completion for all test models."""
        model = test_models[model_key]
        
        payload = {
            "model": model["id"],
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 50
        }
        
        with TestTimer() as timer:
            response = await http_client.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
        
        assert response.status_code == 200
        assert timer.elapsed < performance_thresholds["max_response_time"], \
            f"Response time {timer.elapsed:.3f}s exceeds threshold {performance_thresholds['max_response_time']}s"
        
        data = response.json()
        # Use the assertion function directly
        assert_valid_response_structure(data, expected_chat_response_structure)
        
        # Verify response structure
        assert "id" in data
        assert "object" in data
        assert "created" in data
        assert "model" in data
        assert "choices" in data
        assert "usage" in data
        
        # Verify choices
        assert len(data["choices"]) > 0
        choice = data["choices"][0]
        assert_valid_choice_structure(choice)
        
        # Verify message content
        message = choice["message"]
        assert message["role"] == "assistant"
        assert len(message["content"]) > 0
        
        # Verify usage information
        usage = data["usage"]
        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage
        assert "total_tokens" in usage
        assert usage["total_tokens"] >= usage["prompt_tokens"] + usage["completion_tokens"]
        
        # Verify model information (be flexible as router might map to different model)
        assert isinstance(data["model"], str), "Model should be a string"
        assert len(data["model"]) > 0, "Model should not be empty"
        
        # Verify the response object type
        assert data["object"] == "chat.completion"
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_key", ["local_orange", "gemini_mini", "deepseek_chat"])
    async def test_streaming_chat_completion(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        model_key: str,
        sample_messages: list,
        streaming_test_config: dict,
        performance_thresholds: dict,
        http_client: httpx.AsyncClient
    ):
        """Test streaming chat completion for all test models."""
        model = test_models[model_key]
        
        payload = {
            "model": model["id"],
            "messages": sample_messages,
            "stream": True,
            "max_tokens": streaming_test_config["max_tokens"]
        }
        
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Accept": "text/event-stream"},
                json=payload
            ) as response:
                assert response.status_code == 200
                
                # Collect streaming data
                stream_data = await StreamingResponseParser.collect_stream_content(response)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        # Verify streaming response
        assert stream_data["chunk_count"] > 0, "Should receive at least one chunk"
        assert len(stream_data["content"]) > 0, "Should receive some content"
        assert stream_data["ttft"] is not None, "Should have TTFT measurement"
        assert stream_data["ttft"] < performance_thresholds["max_ttft"], \
            f"TTFT {stream_data['ttft']:.3f}s exceeds threshold {performance_thresholds['max_ttft']}s"
        
        # Calculate and verify performance metrics
        metrics = calculate_ttft_metrics(stream_data)
        violations = assert_performance_thresholds(metrics, performance_thresholds)
        
        assert len(violations) == 0, f"Performance violations: {violations}"
        
        # Verify each chunk has correct structure
        for chunk in stream_data["chunks"]:
            assert "id" in chunk
            assert "object" in chunk
            assert "created" in chunk
            assert "model" in chunk
            assert "choices" in chunk
            
            # Verify streaming format
            assert chunk["object"] == "chat.completion.chunk"
            assert isinstance(chunk["model"], str), "Model should be a string"
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_key", ["local_orange", "gemini_mini", "deepseek_chat"])
    async def test_chat_completion_with_unicode(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        model_key: str,
        unicode_messages: list,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion with Unicode and emoji content."""
        model = test_models[model_key]
        
        payload = {
            "model": model["id"],
            "messages": unicode_messages,
            "stream": False,
            "max_tokens": 100
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0, "Should receive content"
        
        # Should contain Unicode characters
        has_unicode = any(ord(char) > 127 for char in content)
        assert has_unicode, "Response should contain Unicode characters"
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_key", ["local_orange", "gemini_mini", "deepseek_chat"])
    async def test_chat_completion_with_long_message(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        model_key: str,
        long_message: dict,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion with long message content."""
        model = test_models[model_key]
        
        payload = {
            "model": model["id"],
            "messages": [long_message],
            "stream": False,
            "max_tokens": 50
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0, "Should receive content even with long input"
        
        # Verify usage information reflects long input
        usage = data["usage"]
        assert usage["prompt_tokens"] > 100, "Long message should use many tokens"
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_key", ["local_orange", "gemini_mini", "deepseek_chat"])
    async def test_chat_completion_with_multiple_messages(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        model_key: str,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion with multiple messages in conversation."""
        model = test_models[model_key]
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "The capital of France is Paris."},
            {"role": "user", "content": "What is its population?"}
        ]
        
        payload = {
            "model": model["id"],
            "messages": messages,
            "stream": False,
            "max_tokens": 50
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        content = data["choices"][0]["message"]["content"]
        assert len(content) > 0, "Should receive content"
        
        # Should handle conversation context
        assert any(word in content.lower() for word in ["paris", "population", "million"]), \
            "Should respond in context of conversation"
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_key", ["local_orange", "gemini_mini", "deepseek_chat"])
    async def test_chat_completion_parameters(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        model_key: str,
        sample_messages: list,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion with various parameters."""
        model = test_models[model_key]
        
        payload = {
            "model": model["id"],
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 30,
            "temperature": 0.7,
            "top_p": 0.9,
            "presence_penalty": 0.1,
            "frequency_penalty": 0.1
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response respects max_tokens
        content = data["choices"][0]["message"]["content"]
        # Note: This is a rough check as tokenization varies
        assert len(content) > 0, "Should receive content"
        
        # Verify usage information
        usage = data["usage"]
        assert usage["completion_tokens"] <= 30, "Should respect max_tokens limit"
    
    @pytest.mark.asyncio
    async def test_chat_completion_invalid_model(
        self, 
        base_url: str, 
        api_keys: dict, 
        sample_messages: list,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion with invalid model."""
        payload = {
            "model": "invalid/model/name",
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 50
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code in [400, 404], "Should return error for invalid model"
        
        error_data = response.json()
        assert "error" in error_data or "detail" in error_data, "Should return error object"
    
    @pytest.mark.asyncio
    async def test_chat_completion_missing_required_fields(
        self, 
        base_url: str, 
        api_keys: dict,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion with missing required fields."""
        # Missing model field
        payload = {
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 400, "Should return error for missing model"
        
        # Missing messages field
        payload = {
            "model": "local/orange",
            "stream": False
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 400, "Should return error for missing messages"
    
    @pytest.mark.asyncio
    async def test_chat_completion_empty_messages(
        self, 
        base_url: str, 
        api_keys: dict,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion with empty messages array."""
        payload = {
            "model": "local/orange",
            "messages": [],
            "stream": False,
            "max_tokens": 50
        }
        
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 400, "Should return error for empty messages"
    
    @pytest.mark.asyncio
    async def test_chat_completion_authentication(
        self, 
        base_url: str, 
        api_keys: dict, 
        sample_messages: list,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion authentication requirements."""
        payload = {
            "model": "local/orange",
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 50
        }
        
        # Test without authentication
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 401, "Should require authentication"
        
        # Test with invalid authentication
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['invalid']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 401, "Should reject invalid authentication"
    
    @pytest.mark.asyncio
    async def test_streaming_interruption_handling(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test streaming response interruption handling."""
        payload = {
            "model": test_models["local_orange"]["id"],
            "messages": [{"role": "user", "content": "Tell me a long story"}],
            "stream": True,
            "max_tokens": 100
        }
        
        chunks_received = []
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:  # Short timeout to test interruption
                async with client.stream(
                    "POST",
                    f"{base_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_keys['full_access']}", "Accept": "text/event-stream"},
                    json=payload
                ) as response:
                    assert response.status_code == 200
                    
                    async for chunk in StreamingResponseParser.parse_sse_stream(response):
                        chunks_received.append(chunk)
                        
                        # Simulate interruption after a few chunks
                        if len(chunks_received) >= 3:
                            break
        except (httpx.TimeoutException, httpx.ReadTimeout):
            # Expected due to short timeout
            pass
        
        # Should have received some chunks before interruption
        assert len(chunks_received) > 0, "Should receive some chunks before interruption"
    
    @pytest.mark.asyncio
    async def test_concurrent_chat_requests(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test concurrent chat completion requests."""
        model_id = test_models["local_orange"]["id"]
        
        async def make_request(request_id: int):
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": f"Hello from request {request_id}"}],
                "stream": False,
                "max_tokens": 20
            }
            
            response = await http_client.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
            
            return response.status_code == 200
        
        # Make 5 concurrent requests
        tasks = [make_request(i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All requests should succeed
        successful_requests = sum(1 for result in results if result is True)
        assert successful_requests >= 4, f"At least 4 of 5 requests should succeed, got {successful_requests}"
    
    @pytest.mark.asyncio
    async def test_chat_completion_rate_limiting(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test chat completion rate limiting (if implemented)."""
        model_id = test_models["local_orange"]["id"]
        
        # Make rapid requests to test rate limiting
        responses = []
        for i in range(10):
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": f"Request {i}"}],
                "stream": False,
                "max_tokens": 10
            }
            
            response = await http_client.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
            
            responses.append(response)
            
            # Small delay to avoid overwhelming
            await asyncio.sleep(0.1)
        
        # Most requests should succeed
        successful_requests = sum(1 for r in responses if r.status_code == 200)
        assert successful_requests >= 7, f"At least 7 of 10 requests should succeed, got {successful_requests}"
        
        # Check if any were rate limited
        rate_limited = sum(1 for r in responses if r.status_code == 429)
        if rate_limited > 0:
            print(f"Note: {rate_limited} requests were rate limited")
    
    @pytest.mark.asyncio
    async def test_streaming_format_detection(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test that streaming format is correctly detected and handled."""
        model_id = test_models["local_orange"]["id"]
        
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Count from 1 to 5"}],
            "stream": True,
            "max_tokens": 30
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Accept": "text/event-stream"},
                json=payload
            ) as response:
                assert response.status_code == 200
                
                # Check response headers for streaming format
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type or "application/json" in content_type
                
                # Parse streaming response
                stream_data = await StreamingResponseParser.collect_stream_content(response)
                
                # Should receive proper streaming format
                assert stream_data["chunk_count"] > 0, "Should receive streaming chunks"
                assert len(stream_data["content"]) > 0, "Should receive content"
    
    @pytest.mark.asyncio
    async def test_chat_completion_response_consistency(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        sample_messages: list,
        http_client: httpx.AsyncClient
    ):
        """Test that chat completion responses are consistent."""
        model_id = test_models["local_orange"]["id"]
        
        payload = {
            "model": model_id,
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 30,
            "temperature": 0.0  # Low temperature for consistent responses
        }
        
        # Make multiple requests with same parameters
        responses = []
        for _ in range(3):
            response = await http_client.post(
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
            
            assert response.status_code == 200
            responses.append(response.json())
        
        # Responses should be similar (with low temperature)
        # Note: They might not be identical due to other factors
        for response in responses:
            assert "choices" in response
            assert len(response["choices"]) > 0
            assert "content" in response["choices"][0]["message"]
            assert len(response["choices"][0]["message"]["content"]) > 0


class TestChatCompletionStreamingSpecific:
    """Tests specific to streaming functionality."""
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("model_key", ["local_orange", "gemini_mini", "deepseek_chat"])
    async def test_streaming_chunk_structure(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        model_key: str,
        http_client: httpx.AsyncClient
    ):
        """Test that streaming chunks have correct structure."""
        model = test_models[model_key]
        
        payload = {
            "model": model["id"],
            "messages": [{"role": "user", "content": "Hello!"}],
            "stream": True,
            "max_tokens": 20
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Accept": "text/event-stream"},
                json=payload
            ) as response:
                assert response.status_code == 200
                
                chunk_count = 0
                async for chunk in StreamingResponseParser.parse_sse_stream(response):
                    chunk_count += 1
                    
                    # Verify chunk structure
                    assert "id" in chunk
                    assert "object" in chunk
                    assert "created" in chunk
                    assert "model" in chunk
                    assert "choices" in chunk
                    
                    # Verify streaming-specific fields
                    assert chunk["object"] == "chat.completion.chunk"
                    assert isinstance(chunk["model"], str), "Model should be a string"
                    
                    # Verify choices structure
                    choices = chunk["choices"]
                    assert len(choices) > 0
                    
                    choice = choices[0]
                    assert "index" in choice
                    assert "delta" in choice
                    
                    # First chunk should have role in delta
                    if chunk_count == 1:
                        delta = choice["delta"]
                        assert "role" in delta
                        assert delta["role"] == "assistant"
                    else:
                        # Subsequent chunks should have content
                        delta = choice["delta"]
                        if "content" in delta:
                            assert isinstance(delta["content"], str)
                    
                    # Break after a few chunks to avoid long test
                    if chunk_count >= 5:
                        break
                
                assert chunk_count > 0, "Should receive at least one chunk"
    
    @pytest.mark.asyncio
    async def test_streaming_finish_reasons(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test that streaming responses include proper finish reasons."""
        model_id = test_models["local_orange"]["id"]
        
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True,
            "max_tokens": 10  # Low max_tokens to trigger length limit
        }
        
        finish_reasons = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Accept": "text/event-stream"},
                json=payload
            ) as response:
                assert response.status_code == 200
                
                async for chunk in StreamingResponseParser.parse_sse_stream(response):
                    choices = chunk["choices"]
                    if choices:
                        choice = choices[0]
                        if "finish_reason" in choice and choice["finish_reason"] is not None:
                            finish_reasons.append(choice["finish_reason"])
                            break
        
        # Should have a finish reason
        assert len(finish_reasons) > 0, "Should receive finish reason"
        
        # Finish reason should be valid
        valid_reasons = ["stop", "length", "content_filter", "function_call", "tool_calls"]
        assert finish_reasons[0] in valid_reasons, \
            f"Invalid finish reason: {finish_reasons[0]}"
    
    @pytest.mark.asyncio
    async def test_streaming_content_accumulation(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test that streaming content accumulates correctly."""
        model_id = test_models["local_orange"]["id"]
        
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Count from 1 to 5"}],
            "stream": True,
            "max_tokens": 30
        }
        
        accumulated_content = ""
        chunk_contents = []
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Accept": "text/event-stream"},
                json=payload
            ) as response:
                assert response.status_code == 200
                
                async for chunk in StreamingResponseParser.parse_sse_stream(response):
                    choices = chunk["choices"]
                    if choices:
                        choice = choices[0]
                        delta = choice["delta"]
                        
                        if "content" in delta:
                            content = delta["content"]
                            chunk_contents.append(content)
                            accumulated_content += content
        
        # Verify content accumulation
        assert len(accumulated_content) > 0, "Should accumulate content"
        
        # Verify chunk contents combine to full content
        combined_content = "".join(chunk_contents)
        assert combined_content == accumulated_content, "Combined chunks should match accumulated content"
        
        # Verify content makes sense (should contain numbers)
        assert any(char.isdigit() for char in accumulated_content), \
            "Response should contain numbers as requested"


# Helper functions for response validation
def assert_valid_response_structure(response_data: dict, required_fields: list):
    """Assert that response contains all required fields."""
    for field in required_fields:
        assert field in response_data, f"Response missing required field: {field}"


def assert_valid_choice_structure(choice: dict):
    """Assert that chat completion choice has valid structure."""
    required_fields = ["index", "message", "finish_reason"]
    for field in required_fields:
        assert field in choice, f"Choice missing required field: {field}"
    
    # Check message structure
    message = choice["message"]
    assert "role" in message, "Message missing role"
    assert "content" in message, "Message missing content"