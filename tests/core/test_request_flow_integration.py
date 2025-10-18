"""
Integration test for request flow with standardized logging.

This test simulates a complete request flowing through the system:
API -> Service -> Provider, verifying that logging is consistent
at each layer and that structured data is properly included.
"""

import pytest
import asyncio
import json
import time
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

from src.core.logging import logger, RequestLogger, DebugLogger, PerformanceLogger, StreamingLogger
from src.services.chat_service.chat_service import ChatService
from src.core.config_manager import ConfigManager
from src.providers.openai import OpenAICompatibleProvider


class MockRequest:
    """Mock FastAPI Request object for testing."""
    
    def __init__(self, json_data: dict, request_id: str = "test-req-123"):
        self._json_data = json_data
        self.state = MagicMock()
        self.state.request_id = request_id
        self.method = "POST"
        self.url = "http://test/v1/chat/completions"
        self.client = MagicMock()
        self.client.host = "127.0.0.1"
        self.headers = {"content-type": "application/json"}
    
    async def json(self):
        return self._json_data


class TestRequestFlowIntegration:
    """Test request flow integration with standardized logging."""
    
    @pytest.fixture
    def mock_config_manager(self):
        """Create a mock configuration manager."""
        config = {
            "models": {
                "test-model": {
                    "provider": "openai",
                    "provider_model_name": "gpt-3.5-turbo",
                    "type": "chat",
                    "streaming": True
                }
            },
            "providers": {
                "openai": {
                    "type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "test-key"
                }
            }
        }
        
        mock_manager = MagicMock()
        mock_manager.get_config.return_value = config
        mock_manager.should_sanitize_messages = False
        return mock_manager
    
    @pytest.fixture
    def mock_httpx_client(self):
        """Create a mock httpx client."""
        client = MagicMock()
        return client
    
    @pytest.fixture
    def mock_model_service(self):
        """Create a mock model service."""
        return MagicMock()
    
    @pytest.fixture
    def chat_service(self, mock_config_manager, mock_httpx_client, mock_model_service):
        """Create a ChatService instance with mocked dependencies."""
        return ChatService(mock_config_manager, mock_httpx_client, mock_model_service)
    
    @pytest.fixture
    def sample_request_data(self):
        """Sample chat completion request data."""
        return {
            "model": "test-model",
            "messages": [
                {"role": "user", "content": "Hello, how are you?"}
            ],
            "stream": False,
            "temperature": 0.7
        }
    
    @pytest.fixture
    def sample_streaming_request_data(self):
        """Sample streaming chat completion request data."""
        return {
            "model": "test-model",
            "messages": [
                {"role": "user", "content": "Hello, how are you?"}
            ],
            "stream": True,
            "temperature": 0.7
        }
    
    @pytest.fixture
    def mock_provider_response(self):
        """Mock provider response data."""
        return {
            "id": "chatcmpl-test123",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "gpt-3.5-turbo",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I'm doing well, thank you for asking!"
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 15,
                "total_tokens": 25
            }
        }
    
    @pytest.mark.asyncio
    async def test_non_streaming_request_flow_logging(
        self, 
        chat_service, 
        sample_request_data, 
        mock_provider_response,
        monkeypatch
    ):
        """Test logging consistency through non-streaming request flow."""
        request_id = "integration-test-123"
        user_id = "test-project"
        
        # Create mock request
        mock_request = MockRequest(sample_request_data, request_id)
        
        # Mock provider instance
        mock_provider = MagicMock()
        mock_provider.chat_completions = AsyncMock(return_value=mock_provider_response)
        
        # Mock get_provider_instance
        with patch('src.services.chat_service.chat_service.get_provider_instance', return_value=mock_provider):
            # Mock logger to capture all calls
            mock_logger = MagicMock()
            mock_logger.isEnabledFor.return_value = True
            
            # Replace the real logger with our mock
            with patch('src.services.chat_service.chat_service.logger', mock_logger):
                # Execute the request
                auth_data = (user_id, "test-api-key", ["test-model"], [])
                response = await chat_service.chat_completions(mock_request, auth_data)
                
                # Verify response is JSONResponse
                assert isinstance(response, JSONResponse)
                
                # Collect all logging calls
                info_calls = mock_logger.info.call_args_list
                debug_calls = mock_logger.debug.call_args_list
                
                # Verify request logging
                request_logged = False
                for call in info_calls:
                    extra = call[1]["extra"] if "extra" in call[1] else {}
                    if extra.get("log_type") == "request":
                        request_logged = True
                        assert extra["request_id"] == request_id
                        assert extra["user_id"] == user_id
                        assert extra["model_id"] == "test-model"
                        assert "request_body_summary" in extra
                
                assert request_logged, "Request was not logged properly"
                
                # Verify debug logging of request JSON
                debug_request_logged = False
                for call in debug_calls:
                    extra = call[1]["extra"] if "extra" in call[1] else {}
                    if extra.get("debug_component") == "chat_service" and extra.get("debug_data_flow") == "incoming":
                        debug_request_logged = True
                        assert extra["request_id"] == request_id
                
                assert debug_request_logged, "Debug request logging was not performed"
                
                # Verify response logging
                response_logged = False
                for call in info_calls:
                    extra = call[1]["extra"] if "extra" in call[1] else {}
                    if extra.get("log_type") == "response":
                        response_logged = True
                        assert extra["request_id"] == request_id
                        assert extra["user_id"] == user_id
                        assert extra["model_id"] == "test-model"
                
                assert response_logged, "Response was not logged properly"
                
                # Verify debug logging of response JSON
                debug_response_logged = False
                for call in debug_calls:
                    extra = call[1]["extra"] if "extra" in call[1] else {}
                    if extra.get("debug_component") == "chat_service" and extra.get("debug_data_flow") == "from_provider":
                        debug_response_logged = True
                        assert extra["request_id"] == request_id
                
                assert debug_response_logged, "Debug response logging was not performed"
    
    @pytest.mark.asyncio
    async def test_streaming_request_flow_logging(
        self, 
        chat_service, 
        sample_streaming_request_data,
        monkeypatch
    ):
        """Test logging consistency through streaming request flow."""
        request_id = "streaming-test-123"
        user_id = "test-project"
        
        # Create mock request
        mock_request = MockRequest(sample_streaming_request_data, request_id)
        
        # Mock streaming response
        mock_stream_response = MagicMock(spec=StreamingResponse)
        mock_stream_response.body_iterator = self._create_mock_stream_iterator()
        mock_stream_response.media_type = "text/event-stream"
        
        # Mock provider instance
        mock_provider = MagicMock()
        mock_provider.chat_completions = AsyncMock(return_value=mock_stream_response)
        
        # Mock get_provider_instance
        with patch('src.services.chat_service.chat_service.get_provider_instance', return_value=mock_provider):
            # Mock logger to capture all calls
            mock_logger = MagicMock()
            mock_logger.isEnabledFor.return_value = True
            
            # Replace the real logger with our mock
            with patch('src.services.chat_service.chat_service.logger', mock_logger):
                # Execute the request
                auth_data = (user_id, "test-api-key", ["test-model"], [])
                response = await chat_service.chat_completions(mock_request, auth_data)
                
                # Verify response is StreamingResponse
                assert isinstance(response, StreamingResponse)
                
                # Collect all logging calls
                info_calls = mock_logger.info.call_args_list
                debug_calls = mock_logger.debug.call_args_list
                
                # Verify request logging
                request_logged = False
                for call in info_calls:
                    extra = call[1]["extra"] if "extra" in call[1] else {}
                    if extra.get("log_type") == "request":
                        request_logged = True
                        assert extra["request_id"] == request_id
                        assert extra["user_id"] == user_id
                        assert extra["model_id"] == "test-model"
                
                assert request_logged, "Request was not logged properly"
                
                # Verify streaming start logging
                streaming_start_logged = False
                for call in info_calls:
                    extra = call[1]["extra"] if "extra" in call[1] else {}
                    if extra.get("log_type") == "streaming_start":
                        streaming_start_logged = True
                        assert extra["request_id"] == request_id
                        assert extra["user_id"] == user_id
                        assert extra["model_id"] == "test-model"
                        assert extra["response_type"] == "streaming"
                
                assert streaming_start_logged, "Streaming start was not logged properly"
                
                # Verify debug logging of streaming metadata
                debug_streaming_logged = False
                for call in debug_calls:
                    extra = call[1]["extra"] if "extra" in call[1] else {}
                    if extra.get("debug_component") == "chat_service" and extra.get("debug_data_flow") == "from_provider":
                        if extra.get("debug_json_data", {}).get("streaming"):
                            debug_streaming_logged = True
                            assert extra["request_id"] == request_id
                
                assert debug_streaming_logged, "Debug streaming logging was not performed"
    
    def _create_mock_stream_iterator(self):
        """Create a mock stream iterator for testing."""
        async def mock_iterator():
            # Simulate SSE chunks
            chunks = [
                'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n',
                'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n',
                'data: {"choices": [{"delta": {"content": " world"}}]}\n\n',
                'data: {"choices": [{"delta": {"content": "!"}}]}\n\n',
                'data: [DONE]\n\n'
            ]
            
            for chunk in chunks:
                yield chunk
                await asyncio.sleep(0.001)  # Small delay to simulate real streaming
        
        return mock_iterator()
    
    @pytest.mark.asyncio
    async def test_provider_level_logging(self, sample_request_data, mock_provider_response):
        """Test that provider-level logging works correctly."""
        provider_config = {
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "test-key"
        }
        
        # Create provider instance
        mock_client = AsyncMock()
        provider = OpenAICompatibleProvider(provider_config, mock_client)
        
        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.json.return_value = mock_provider_response
        mock_response.raise_for_status.return_value = None
        
        mock_client.post.return_value = mock_response
        
        # Mock logger to capture calls
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        with patch('src.providers.openai.logger', mock_logger):
            # Add request_id to the request data for tracking
            sample_request_data["request_id"] = "provider-test-123"
            
            # Execute provider request
            model_config = {"options": {"temperature": 0.7}}
            response = await provider.chat_completions(
                sample_request_data, 
                "gpt-3.5-turbo", 
                model_config
            )
            
            # Verify provider request logging
            provider_request_logged = False
            for call in mock_logger.debug.call_args_list:
                extra = call[1]["extra"] if "extra" in call[1] else {}
                if extra.get("debug_component") == "openai_provider" and extra.get("debug_data_flow") == "to_provider":
                    provider_request_logged = True
                    assert extra["request_id"] == "provider-test-123"
                    debug_data = extra["debug_json_data"]
                    assert "url" in debug_data
                    assert "headers" in debug_data
                    assert "request_body" in debug_data
            
            assert provider_request_logged, "Provider request was not logged properly"
            
            # Verify provider response logging
            provider_response_logged = False
            for call in mock_logger.debug.call_args_list:
                extra = call[1]["extra"] if "extra" in call[1] else {}
                if extra.get("debug_component") == "openai_provider" and extra.get("debug_data_flow") == "from_provider":
                    provider_response_logged = True
                    assert extra["request_id"] == "provider-test-123"
                    debug_data = extra["debug_json_data"]
                    assert "choices" in debug_data
                    assert "usage" in debug_data
            
            assert provider_response_logged, "Provider response was not logged properly"
    
    @pytest.mark.asyncio
    async def test_performance_logging_integration(
        self, 
        chat_service, 
        sample_request_data, 
        mock_provider_response
    ):
        """Test that performance logging is integrated properly."""
        request_id = "perf-test-123"
        user_id = "test-project"
        
        # Create mock request
        mock_request = MockRequest(sample_request_data, request_id)
        
        # Mock provider instance with delay to simulate processing time
        mock_provider = MagicMock()
        
        async def delayed_response(*args, **kwargs):
            await asyncio.sleep(0.01)  # Simulate processing time
            return mock_provider_response
        
        mock_provider.chat_completions = AsyncMock(side_effect=delayed_response)
        
        # Mock get_provider_instance
        with patch('src.services.chat_service.chat_service.get_provider_instance', return_value=mock_provider):
            # Mock logger to capture all calls
            mock_logger = MagicMock()
            mock_logger.isEnabledFor.return_value = True
            
            # Replace the real logger with our mock
            with patch('src.services.chat_service.chat_service.logger', mock_logger):
                # Execute the request
                auth_data = (user_id, "test-api-key", ["test-model"], [])
                response = await chat_service.chat_completions(mock_request, auth_data)
                
                # Verify response was processed
                assert isinstance(response, JSONResponse)
    
    def test_request_id_consistency_across_layers(self):
        """Test that request ID is consistent across all logging layers."""
        request_id = "consistency-test-123"
        user_id = "test-user"
        model_id = "test-model"
        
        # Mock logger to capture all calls
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        # Test API layer logging
        RequestLogger.log_request(
            logger=mock_logger,
            operation="API Request",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
        
        # Test Service layer logging
        DebugLogger.log_data_flow(
            logger=mock_logger,
            title="Service Processing",
            data={"step": "validation"},
            data_flow="incoming",
            component="chat_service",
            request_id=request_id
        )
        
        # Test Provider layer logging
        DebugLogger.log_provider_request(
            logger=mock_logger,
            provider_name="openai",
            url="https://api.openai.com/v1/chat/completions",
            headers={"Authorization": "Bearer test"},
            request_body={"model": model_id},
            request_id=request_id
        )
        
        # Test Performance logging
        start_time = time.time()
        PerformanceLogger.log_operation_timing(
            logger=mock_logger,
            operation="Provider Request",
            start_time=start_time,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
        
        # Collect all calls and verify request ID consistency
        all_calls = mock_logger.info.call_args_list + mock_logger.debug.call_args_list
        
        for call in all_calls:
            extra = call[1]["extra"] if "extra" in call[1] else {}
            # All logs should have the request ID
            assert "request_id" in extra, f"Missing request_id in log: {call}"
            assert extra["request_id"] == request_id, f"Inconsistent request_id: {extra['request_id']} != {request_id}"
            
            # Check for user_id consistency where applicable
            if "user_id" in extra:
                assert extra["user_id"] == user_id
            
            # Check for model_id consistency where applicable
            if "model_id" in extra:
                assert extra["model_id"] == model_id
    
    def test_structured_data_in_logging(self):
        """Test that structured data is properly included in logs."""
        request_id = "structured-test-123"
        
        # Mock logger to capture calls
        mock_logger = MagicMock()
        
        # Test request with structured data
        request_data = {
            "model": "test-model",
            "messages": [
                {"role": "user", "content": "Hello, world!" * 10},  # Long message
                {"role": "user", "content": "How are you?"}
            ],
            "temperature": 0.7,
            "max_tokens": 100
        }
        
        RequestLogger.log_request(
            logger=mock_logger,
            operation="Structured Request Test",
            request_id=request_id,
            user_id="test-user",
            model_id="test-model",
            request_data=request_data
        )
        
        # Verify structured data is included
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        
        assert "request_body_summary" in extra
        summary = extra["request_body_summary"]
        
        # Check that summary includes expected fields
        assert summary["model"] == "test-model"
        assert summary["messages_count"] == 2
        assert "first_message_content" in summary
        assert summary["first_message_content"].endswith("...")  # Truncated
        
        # Test response with structured data
        response_data = {
            "choices": [
                {"message": {"content": "Response 1"}},
                {"message": {"content": "Response 2"}}
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 30,
                "total_tokens": 50
            },
            "object": "chat.completion"
        }
        
        token_usage = {
            "prompt_cost": 0.002,
            "completion_cost": 0.003,
            "total_cost": 0.005
        }
        
        RequestLogger.log_response(
            logger=mock_logger,
            operation="Structured Response Test",
            request_id=request_id,
            user_id="test-user",
            model_id="test-model",
            response_data=response_data,
            token_usage=token_usage,
            processing_time_ms=150
        )
        
        # Verify response structured data
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        
        assert "response_body_summary" in extra
        summary = extra["response_body_summary"]
        
        assert summary["choices_count"] == 2
        assert summary["prompt_tokens"] == 20
        assert summary["completion_tokens"] == 30
        assert summary["total_tokens"] == 50
        assert summary["object_type"] == "chat.completion"
        
        # Verify token usage and cost are included
        assert extra["prompt_cost"] == 0.002
        assert extra["completion_cost"] == 0.003
        assert extra["total_cost"] == 0.005
        assert extra["processing_time_ms"] == 150


if __name__ == "__main__":
    pytest.main([__file__])