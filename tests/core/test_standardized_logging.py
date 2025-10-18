"""
Tests for the standardized logging implementation.

This test suite validates that the centralized logging system works correctly,
maintains consistent formatting, and can be imported across all modules.
"""

import pytest
import logging
import json
import time
import tempfile
import os
from unittest.mock import patch, MagicMock
from io import StringIO
from pathlib import Path

from src.core.logging import (
    logger,
    setup_logging,
    RequestLogger,
    DebugLogger,
    PerformanceLogger,
    StreamingLogger,
    Logger
)
from src.core.logging.config import JsonFormatter


class TestLoggingImports:
    """Test that all logging components can be imported successfully."""
    
    def test_import_main_components(self):
        """Test importing main logging components."""
        from src.core.logging import logger, setup_logging
        assert logger is not None
        assert callable(setup_logging)
    
    def test_import_logger_utilities(self):
        """Test importing logger utility classes."""
        from src.core.logging import RequestLogger, DebugLogger, PerformanceLogger, StreamingLogger
        assert RequestLogger is not None
        assert DebugLogger is not None
        assert PerformanceLogger is not None
        assert StreamingLogger is not None
    
    def test_import_logger_class(self):
        """Test importing the main Logger class."""
        from src.core.logging import Logger
        assert Logger is not None
    
    def test_module_imports_from_api_main(self):
        """Test that API main can import logging components."""
        # This simulates the import pattern used in src/api/main.py
        from src.core.logging import logger, RequestLogger, DebugLogger, PerformanceLogger
        assert logger is not None
        assert RequestLogger is not None
        assert DebugLogger is not None
        assert PerformanceLogger is not None
    
    def test_module_imports_from_services(self):
        """Test that service modules can import logging components."""
        # This simulates the import pattern used in service modules
        from src.core.logging import logger, RequestLogger, DebugLogger, PerformanceLogger, StreamingLogger
        assert logger is not None
        assert RequestLogger is not None
        assert DebugLogger is not None
        assert PerformanceLogger is not None
        assert StreamingLogger is not None


class TestJsonFormatter:
    """Test the JSON formatter for structured logging."""
    
    def test_basic_log_formatting(self):
        """Test basic log record formatting."""
        formatter = JsonFormatter()
        
        # Create a log record
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        log_data = json.loads(formatted)
        
        assert log_data["level"] == "INFO"
        assert log_data["message"] == "Test message"
        assert "timestamp" in log_data
    
    def test_custom_attributes_formatting(self):
        """Test formatting with custom attributes."""
        formatter = JsonFormatter()
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        # Add custom attributes
        record.request_id = "req-123"
        record.user_id = "user-456"
        record.model_id = "gpt-4"
        
        formatted = formatter.format(record)
        log_data = json.loads(formatted)
        
        assert log_data["request_id"] == "req-123"
        assert log_data["user_id"] == "user-456"
        assert log_data["model_id"] == "gpt-4"
    
    def test_all_supported_attributes(self):
        """Test formatting with all supported attributes."""
        formatter = JsonFormatter()
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        # Add all supported attributes
        record.request_id = "req-123"
        record.user_id = "user-456"
        record.model_id = "gpt-4"
        record.log_type = "request"
        record.method = "POST"
        record.url = "/v1/chat/completions"
        record.request_body_summary = {"model": "gpt-4"}
        record.http_status_code = 200
        record.process_time_ms = 150
        record.prompt_tokens = 10
        record.completion_tokens = 20
        record.total_tokens = 30
        record.prompt_cost = 0.001
        record.completion_cost = 0.002
        record.total_cost = 0.003
        record.response_body_summary = {"choices": 1}
        record.error_message = "Test error"
        record.error_code = "test_error"
        record.detail = "Error detail"
        record.api_key = "sk-test"
        record.project_name = "test_project"
        record.debug_json_data = {"debug": "data"}
        record.debug_data_flow = "incoming"
        record.debug_component = "middleware"
        
        formatted = formatter.format(record)
        log_data = json.loads(formatted)
        
        # Verify all attributes are included
        assert log_data["request_id"] == "req-123"
        assert log_data["user_id"] == "user-456"
        assert log_data["model_id"] == "gpt-4"
        assert log_data["log_type"] == "request"
        assert log_data["method"] == "POST"
        assert log_data["url"] == "/v1/chat/completions"
        assert log_data["request_body_summary"] == {"model": "gpt-4"}
        assert log_data["http_status_code"] == 200
        assert log_data["process_time_ms"] == 150
        assert log_data["prompt_tokens"] == 10
        assert log_data["completion_tokens"] == 20
        assert log_data["total_tokens"] == 30
        assert log_data["prompt_cost"] == 0.001
        assert log_data["completion_cost"] == 0.002
        assert log_data["total_cost"] == 0.003
        assert log_data["response_body_summary"] == {"choices": 1}
        assert log_data["error_message"] == "Test error"
        assert log_data["error_code"] == "test_error"
        assert log_data["detail"] == "Error detail"
        assert log_data["api_key"] == "sk-test"
        assert log_data["project_name"] == "test_project"
        assert log_data["debug_json_data"] == {"debug": "data"}
        assert log_data["debug_data_flow"] == "incoming"
        assert log_data["debug_component"] == "middleware"


class TestRequestLogger:
    """Test the RequestLogger utility."""
    
    def test_log_request_minimal(self):
        """Test logging a minimal request."""
        mock_logger = MagicMock()
        
        RequestLogger.log_request(
            logger=mock_logger,
            operation="Test Request",
            request_id="req-123",
            user_id="user-456"
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Test Request"
        
        extra = call_args[1]["extra"]
        assert extra["log_type"] == "request"
        assert extra["request_id"] == "req-123"
        assert extra["user_id"] == "user-456"
    
    def test_log_request_full(self):
        """Test logging a full request with all parameters."""
        mock_logger = MagicMock()
        
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello, world!" * 10}]
        }
        
        RequestLogger.log_request(
            logger=mock_logger,
            operation="Chat Completion Request",
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            provider_name="openai",
            request_data=request_data,
            additional_data={"custom_field": "custom_value"}
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        
        assert extra["model_id"] == "gpt-4"
        assert extra["provider_name"] == "openai"
        assert extra["custom_field"] == "custom_value"
        
        # Check request summary
        summary = extra["request_body_summary"]
        assert summary["model"] == "gpt-4"
        assert summary["messages_count"] == 1
        assert "Hello, world!" in summary["first_message_content"]
        assert summary["first_message_content"].endswith("...")
    
    def test_log_response_minimal(self):
        """Test logging a minimal response."""
        mock_logger = MagicMock()
        
        RequestLogger.log_response(
            logger=mock_logger,
            operation="Test Response",
            request_id="req-123",
            user_id="user-456"
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Test Response"
        
        extra = call_args[1]["extra"]
        assert extra["log_type"] == "response"
        assert extra["request_id"] == "req-123"
        assert extra["user_id"] == "user-456"
        assert extra["http_status_code"] == 200
    
    def test_log_response_full(self):
        """Test logging a full response with all parameters."""
        mock_logger = MagicMock()
        
        response_data = {
            "choices": [{"message": {"content": "Response"}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30
            },
            "object": "chat.completion"
        }
        
        token_usage = {
            "prompt_cost": 0.001,
            "completion_cost": 0.002,
            "total_cost": 0.003
        }
        
        RequestLogger.log_response(
            logger=mock_logger,
            operation="Chat Completion Response",
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            provider_name="openai",
            status_code=200,
            response_data=response_data,
            processing_time_ms=150,
            token_usage=token_usage,
            additional_data={"custom_field": "custom_value"}
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        
        assert extra["model_id"] == "gpt-4"
        assert extra["provider_name"] == "openai"
        assert extra["processing_time_ms"] == 150
        assert extra["custom_field"] == "custom_value"
        assert extra["prompt_cost"] == 0.001
        assert extra["completion_cost"] == 0.002
        assert extra["total_cost"] == 0.003
        
        # Check response summary
        summary = extra["response_body_summary"]
        assert summary["choices_count"] == 1
        assert summary["prompt_tokens"] == 10
        assert summary["completion_tokens"] == 20
        assert summary["total_tokens"] == 30
        assert summary["object_type"] == "chat.completion"


class TestDebugLogger:
    """Test the DebugLogger utility."""
    
    def test_log_data_flow_with_data(self):
        """Test logging data flow with direct data."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        test_data = {"key": "value", "number": 42}
        
        DebugLogger.log_data_flow(
            logger=mock_logger,
            title="DEBUG: Test Data",
            data=test_data,
            data_flow="incoming",
            component="test_component",
            request_id="req-123"
        )
        
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert call_args[0][0] == "DEBUG: Test Data"
        
        extra = call_args[1]["extra"]
        assert extra["debug_json_data"] == test_data
        assert extra["debug_data_flow"] == "incoming"
        assert extra["debug_component"] == "test_component"
        assert extra["request_id"] == "req-123"
    
    def test_log_data_flow_with_callable(self):
        """Test logging data flow with callable data (lazy evaluation)."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        def expensive_data():
            return {"expensive": "computation"}
        
        DebugLogger.log_data_flow(
            logger=mock_logger,
            title="DEBUG: Expensive Data",
            data=expensive_data,
            data_flow="outgoing",
            component="test_component",
            request_id="req-123"
        )
        
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        extra = call_args[1]["extra"]
        assert extra["debug_json_data"] == {"expensive": "computation"}
    
    def test_log_data_flow_disabled(self):
        """Test that data flow logging is skipped when debug is disabled."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = False
        
        def expensive_data():
            pytest.fail("Expensive data should not be computed when debug is disabled")
        
        DebugLogger.log_data_flow(
            logger=mock_logger,
            title="DEBUG: Should Not Execute",
            data=expensive_data,
            data_flow="incoming",
            component="test_component",
            request_id="req-123"
        )
        
        mock_logger.debug.assert_not_called()
    
    def test_log_provider_request(self):
        """Test logging provider request."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        DebugLogger.log_provider_request(
            logger=mock_logger,
            provider_name="openai",
            url="https://api.openai.com/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            request_body={"model": "gpt-4", "messages": []},
            request_id="req-123"
        )
        
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert "DEBUG: Openai Request" == call_args[0][0]
        
        extra = call_args[1]["extra"]
        assert extra["debug_data_flow"] == "to_provider"
        assert extra["debug_component"] == "openai_provider"
        assert extra["request_id"] == "req-123"
        assert extra["debug_json_data"]["url"] == "https://api.openai.com/v1/chat/completions"
    
    def test_log_provider_response(self):
        """Test logging provider response."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        response_data = {"choices": [{"message": {"content": "Hello"}}]}
        
        DebugLogger.log_provider_response(
            logger=mock_logger,
            provider_name="anthropic",
            response_data=response_data,
            request_id="req-123"
        )
        
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert "DEBUG: Anthropic Response" == call_args[0][0]
        
        extra = call_args[1]["extra"]
        assert extra["debug_data_flow"] == "from_provider"
        assert extra["debug_component"] == "anthropic_provider"
        assert extra["request_id"] == "req-123"
        assert extra["debug_json_data"] == response_data


class TestPerformanceLogger:
    """Test the PerformanceLogger utility."""
    
    def test_log_operation_timing(self):
        """Test logging operation timing."""
        mock_logger = MagicMock()
        start_time = time.time()
        
        # Sleep a bit to ensure measurable time
        time.sleep(0.01)
        
        PerformanceLogger.log_operation_timing(
            logger=mock_logger,
            operation="Test Operation",
            start_time=start_time,
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            additional_metrics={"custom_metric": 100}
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Performance: Test Operation"
        
        extra = call_args[1]["extra"]
        assert extra["log_type"] == "performance"
        assert extra["operation"] == "Test Operation"
        assert extra["request_id"] == "req-123"
        assert extra["user_id"] == "user-456"
        assert extra["model_id"] == "gpt-4"
        assert extra["custom_metric"] == 100
        assert extra["start_time"] == start_time
        assert extra["duration_ms"] > 0
    
    def test_create_timing_context(self):
        """Test creating a timing context."""
        context = PerformanceLogger.create_timing_context(
            operation="Test Operation",
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4"
        )
        
        assert context["operation"] == "Test Operation"
        assert context["request_id"] == "req-123"
        assert context["user_id"] == "user-456"
        assert context["model_id"] == "gpt-4"
        assert "start_time" in context
        assert context["start_time"] > 0
    
    def test_complete_timing_context(self):
        """Test completing a timing context."""
        mock_logger = MagicMock()
        start_time = time.time()
        time.sleep(0.01)
        
        context = {
            "operation": "Test Operation",
            "start_time": start_time,
            "request_id": "req-123",
            "user_id": "user-456",
            "model_id": "gpt-4"
        }
        
        PerformanceLogger.complete_timing_context(
            logger=mock_logger,
            context=context,
            additional_metrics={"custom_metric": 200}
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert extra["custom_metric"] == 200
        assert extra["duration_ms"] > 0
    
    def test_timing_context_manager(self):
        """Test the timing context manager."""
        mock_logger = MagicMock()
        
        with PerformanceLogger.timing_context(
            logger=mock_logger,
            operation="Test Operation",
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            additional_metrics={"custom_metric": 300}
        ):
            # Simulate some work
            time.sleep(0.01)
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert extra["custom_metric"] == 300
        assert extra["duration_ms"] > 0


class TestStreamingLogger:
    """Test the StreamingLogger utility."""
    
    def test_log_streaming_start(self):
        """Test logging streaming start."""
        mock_logger = MagicMock()
        
        StreamingLogger.log_streaming_start(
            logger=mock_logger,
            operation="Chat Completion Streaming",
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            additional_data={"custom_field": "custom_value"}
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Initiating Chat Completion Streaming"
        
        extra = call_args[1]["extra"]
        assert extra["log_type"] == "streaming_start"
        assert extra["request_id"] == "req-123"
        assert extra["user_id"] == "user-456"
        assert extra["model_id"] == "gpt-4"
        assert extra["response_type"] == "streaming"
        assert extra["custom_field"] == "custom_value"
    
    def test_log_streaming_end(self):
        """Test logging streaming end."""
        mock_logger = MagicMock()
        
        token_usage = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30
        }
        
        StreamingLogger.log_streaming_end(
            logger=mock_logger,
            operation="Chat Completion Streaming",
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            chunk_count=5,
            processing_time_ms=200,
            token_usage=token_usage,
            additional_data={"custom_field": "custom_value"}
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Completed Chat Completion Streaming"
        
        extra = call_args[1]["extra"]
        assert extra["log_type"] == "streaming_end"
        assert extra["request_id"] == "req-123"
        assert extra["user_id"] == "user-456"
        assert extra["model_id"] == "gpt-4"
        assert extra["chunk_count"] == 5
        assert extra["processing_time_ms"] == 200
        assert extra["prompt_tokens"] == 10
        assert extra["completion_tokens"] == 20
        assert extra["total_tokens"] == 30
        assert extra["custom_field"] == "custom_value"
    
    def test_log_streaming_chunk(self):
        """Test logging streaming chunk."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        chunk_data = {"choices": [{"delta": {"content": "Hello"}}]}
        
        StreamingLogger.log_streaming_chunk(
            logger=mock_logger,
            chunk_data=chunk_data,
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            chunk_number=3
        )
        
        mock_logger.debug.assert_called_once()
        call_args = mock_logger.debug.call_args
        assert call_args[0][0] == "Streaming chunk 3"
        
        extra = call_args[1]["extra"]
        assert extra["log_type"] == "streaming_chunk"
        assert extra["request_id"] == "req-123"
        assert extra["user_id"] == "user-456"
        assert extra["model_id"] == "gpt-4"
        assert extra["chunk_number"] == 3
        assert extra["chunk_size"] > 0
    
    def test_log_streaming_chunk_disabled(self):
        """Test that streaming chunk logging is skipped when debug is disabled."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = False
        
        chunk_data = {"choices": [{"delta": {"content": "Hello"}}]}
        
        StreamingLogger.log_streaming_chunk(
            logger=mock_logger,
            chunk_data=chunk_data,
            request_id="req-123",
            user_id="user-456",
            model_id="gpt-4",
            chunk_number=3
        )
        
        mock_logger.debug.assert_not_called()


class TestLoggerClass:
    """Test the main Logger class."""
    
    def test_logger_initialization(self):
        """Test Logger class initialization."""
        test_logger = Logger()
        assert test_logger.logger is not None
        assert test_logger.request_logger is not None
        assert test_logger.debug_logger is not None
        assert test_logger.performance_logger is not None
        assert test_logger.streaming_logger is not None
    
    def test_logger_with_custom_instance(self):
        """Test Logger class with custom logger instance."""
        custom_logger = logging.getLogger("custom")
        test_logger = Logger(custom_logger)
        assert test_logger.logger == custom_logger
    
    def test_is_debug_enabled(self):
        """Test debug enabled check."""
        test_logger = Logger()
        # Should return a boolean
        assert isinstance(test_logger.is_debug_enabled(), bool)
    
    def test_basic_logging_methods(self):
        """Test basic logging methods."""
        mock_logger = MagicMock()
        test_logger = Logger(mock_logger)
        
        test_logger.info("Test info", extra={"custom": "value"})
        mock_logger.info.assert_called_once_with("Test info", extra={"custom": "value"})
        
        test_logger.debug("Test debug")
        mock_logger.debug.assert_called_once_with("Test debug")
        
        test_logger.warning("Test warning")
        mock_logger.warning.assert_called_once_with("Test warning")
        
        test_logger.error("Test error", exc_info=True)
        mock_logger.error.assert_called_once_with("Test error", exc_info=True)
        
        test_logger.critical("Test critical")
        mock_logger.critical.assert_called_once_with("Test critical")
    
    def test_convenience_methods(self):
        """Test convenience methods that delegate to utilities."""
        mock_logger = MagicMock()
        test_logger = Logger(mock_logger)
        
        # Test log_request
        test_logger.log_request(
            operation="Test Request",
            request_id="req-123",
            user_id="user-456"
        )
        mock_logger.info.assert_called()
        
        # Reset mock
        mock_logger.reset_mock()
        
        # Test log_response
        test_logger.log_response(
            operation="Test Response",
            request_id="req-123",
            user_id="user-456"
        )
        mock_logger.info.assert_called()
        
        # Reset mock
        mock_logger.reset_mock()
        
        # Test log_debug_data
        mock_logger.isEnabledFor.return_value = True
        test_logger.log_debug_data(
            title="Debug Data",
            data={"test": "data"},
            data_flow="incoming",
            component="test",
            request_id="req-123"
        )
        mock_logger.debug.assert_called()
        
        # Reset mock
        mock_logger.reset_mock()
        
        # Test log_performance
        start_time = time.time()
        test_logger.log_performance(
            operation="Test Operation",
            start_time=start_time,
            request_id="req-123",
            user_id="user-456"
        )
        mock_logger.info.assert_called()


class TestRequestIdTracking:
    """Test request ID tracking through the call chain."""
    
    def test_request_id_propagation(self):
        """Test that request ID is properly propagated through different loggers."""
        mock_logger = MagicMock()
        request_id = "test-request-123"
        user_id = "test-user-456"
        model_id = "gpt-4"
        
        # Log request
        RequestLogger.log_request(
            logger=mock_logger,
            operation="Test Request",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
        
        # Verify request ID is in the log
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert extra["request_id"] == request_id
        
        # Reset mock
        mock_logger.reset_mock()
        
        # Log debug data with same request ID
        mock_logger.isEnabledFor.return_value = True
        DebugLogger.log_data_flow(
            logger=mock_logger,
            title="Debug Data",
            data={"test": "data"},
            data_flow="incoming",
            component="test",
            request_id=request_id
        )
        
        # Verify request ID is preserved
        call_args = mock_logger.debug.call_args
        extra = call_args[1]["extra"]
        assert extra["request_id"] == request_id
        
        # Reset mock
        mock_logger.reset_mock()
        
        # Log performance with same request ID
        start_time = time.time()
        PerformanceLogger.log_operation_timing(
            logger=mock_logger,
            operation="Test Operation",
            start_time=start_time,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
        
        # Verify request ID is preserved
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert extra["request_id"] == request_id
        
        # Reset mock
        mock_logger.reset_mock()
        
        # Log streaming with same request ID
        StreamingLogger.log_streaming_start(
            logger=mock_logger,
            operation="Test Streaming",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
        
        # Verify request ID is preserved
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert extra["request_id"] == request_id


class TestIntegration:
    """Integration tests for the logging system."""
    
    def test_end_to_end_logging_flow(self):
        """Test a complete end-to-end logging flow."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        request_id = "integration-test-123"
        user_id = "integration-user-456"
        model_id = "gpt-4"
        
        # 1. Log incoming request
        RequestLogger.log_request(
            logger=mock_logger,
            operation="Chat Completion Request",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            request_data={
                "model": model_id,
                "messages": [{"role": "user", "content": "Hello!"}]
            }
        )
        
        # 2. Log debug data flow
        DebugLogger.log_data_flow(
            logger=mock_logger,
            title="DEBUG: Request to Provider",
            data={"provider": "openai", "processed": True},
            data_flow="to_provider",
            component="chat_service",
            request_id=request_id
        )
        
        # 3. Log performance timing
        start_time = time.time()
        time.sleep(0.01)  # Simulate processing
        PerformanceLogger.log_operation_timing(
            logger=mock_logger,
            operation="Provider Request",
            start_time=start_time,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
        
        # 4. Log streaming start
        StreamingLogger.log_streaming_start(
            logger=mock_logger,
            operation="Chat Completion Streaming",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
        
        # 5. Log streaming chunks
        for i in range(3):
            StreamingLogger.log_streaming_chunk(
                logger=mock_logger,
                chunk_data={"choices": [{"delta": {"content": f"chunk {i}"}}]},
                request_id=request_id,
                user_id=user_id,
                model_id=model_id,
                chunk_number=i + 1
            )
        
        # 6. Log streaming end
        StreamingLogger.log_streaming_end(
            logger=mock_logger,
            operation="Chat Completion Streaming",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            chunk_count=3,
            processing_time_ms=100,
            token_usage={"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25}
        )
        
        # 7. Log final response
        RequestLogger.log_response(
            logger=mock_logger,
            operation="Chat Completion Response",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            status_code=200,
            response_data={"choices": [{"message": {"content": "Hello!"}}]},
            processing_time_ms=150
        )
        
        # Verify all calls were made with correct request ID
        calls = mock_logger.info.call_args_list + mock_logger.debug.call_args_list
        
        for call in calls:
            extra = call[1]["extra"]
            assert extra["request_id"] == request_id
            # user_id is not included in all log types (e.g., streaming chunks)
            if "user_id" in extra:
                assert extra["user_id"] == user_id
            if "model_id" in extra:
                assert extra["model_id"] == model_id
    
    def test_logger_class_integration(self):
        """Test integration using the main Logger class."""
        mock_logger = MagicMock()
        mock_logger.isEnabledFor.return_value = True
        
        test_logger = Logger(mock_logger)
        
        request_id = "logger-integration-123"
        user_id = "logger-user-456"
        
        # Use the Logger class for all operations
        test_logger.log_request(
            operation="Test Request",
            request_id=request_id,
            user_id=user_id,
            model_id="gpt-4"
        )
        
        with test_logger.timing_context(
            operation="Test Operation",
            request_id=request_id,
            user_id=user_id,
            model_id="gpt-4"
        ):
            test_logger.log_debug_data(
                title="Debug Info",
                data={"test": "data"},
                data_flow="incoming",
                component="test",
                request_id=request_id
            )
        
        test_logger.log_streaming_start(
            operation="Test Streaming",
            request_id=request_id,
            user_id=user_id,
            model_id="gpt-4"
        )
        
        test_logger.log_streaming_end(
            operation="Test Streaming",
            request_id=request_id,
            user_id=user_id,
            model_id="gpt-4",
            chunk_count=1,
            processing_time_ms=50
        )
        
        test_logger.log_response(
            operation="Test Response",
            request_id=request_id,
            user_id=user_id,
            model_id="gpt-4",
            status_code=200
        )
        
        # Verify all calls were made
        assert mock_logger.info.called
        assert mock_logger.debug.called
        
        # Verify request ID consistency
        calls = mock_logger.info.call_args_list + mock_logger.debug.call_args_list
        for call in calls:
            extra = call[1]["extra"]
            assert extra["request_id"] == request_id
            # user_id is not included in all log types (e.g., debug logs)
            if "user_id" in extra:
                assert extra["user_id"] == user_id


class TestSetupLogging:
    """Test the setup_logging function."""
    
    def test_setup_logging_creates_logger(self):
        """Test that setup_logging creates a configured logger."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("os.makedirs"):
                with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
                    test_logger = setup_logging()
                    assert isinstance(test_logger, logging.Logger)
                    assert test_logger.name == "nnp-llm-router"
                    assert test_logger.level == logging.DEBUG
    
    def test_setup_logging_default_level(self):
        """Test setup_logging with default log level."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("os.makedirs"):
                with patch.dict(os.environ, {}, clear=True):
                    test_logger = setup_logging()
                    assert test_logger.level == logging.INFO


if __name__ == "__main__":
    pytest.main([__file__])