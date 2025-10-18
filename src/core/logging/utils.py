"""
Unified logging utility methods to replace repetitive logging patterns.

This module provides centralized logging utilities that eliminate code duplication
while maintaining identical log output formats. These utilities replace the 72
instances of repetitive logging patterns across the codebase.
"""

import logging
import time
from typing import Dict, Any, Optional, Union, Callable
from contextlib import contextmanager


class RequestLogger:
    """Centralized request and response logging utility."""
    
    @staticmethod
    def log_request(
        logger: logging.Logger,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        request_data: Optional[Dict[str, Any]] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log incoming request with standardized format.
        
        Args:
            logger: Logger instance to use
            operation: Operation name (e.g., "Chat Completion Request")
            request_id: Unique request identifier
            user_id: User identifier
            model_id: Model identifier if applicable
            provider_name: Provider name if applicable
            request_data: Request data for summary
            additional_data: Additional data to include in log
        """
        log_extra = {
            "log_type": "request",
            "request_id": request_id,
            "user_id": user_id
        }
        
        if model_id:
            log_extra["model_id"] = model_id
        if provider_name:
            log_extra["provider_name"] = provider_name
            
        # Create request body summary
        request_summary = {}
        if request_data:
            if "model" in request_data:
                request_summary["model"] = request_data["model"]
            if "messages" in request_data:
                messages = request_data["messages"]
                request_summary["messages_count"] = len(messages)
                if messages and "content" in messages[0]:
                    content = messages[0]["content"]
                    request_summary["first_message_content"] = (
                        content[:100] + "..." if len(content) > 100 else content
                    )
            if "input" in request_data:
                input_data = request_data["input"]
                if isinstance(input_data, list):
                    request_summary["input_count"] = len(input_data)
                    request_summary["input_type"] = "list"
                    if input_data and isinstance(input_data[0], str):
                        content = input_data[0]
                        request_summary["first_input_content"] = (
                            content[:100] + "..." if len(content) > 100 else content
                        )
                elif isinstance(input_data, str):
                    request_summary["input_type"] = "string"
                    request_summary["input_length"] = len(input_data)
                    request_summary["input_content"] = (
                        input_data[:100] + "..." if len(input_data) > 100 else input_data
                    )
        
        log_extra["request_body_summary"] = request_summary
        
        if additional_data:
            log_extra.update(additional_data)
        
        logger.info(operation, extra=log_extra)
    
    @staticmethod
    def log_response(
        logger: logging.Logger,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: Optional[str] = None,
        provider_name: Optional[str] = None,
        status_code: int = 200,
        response_data: Optional[Dict[str, Any]] = None,
        processing_time_ms: Optional[int] = None,
        token_usage: Optional[Dict[str, int]] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log response with standardized format.
        
        Args:
            logger: Logger instance to use
            operation: Operation name (e.g., "Chat Completion Response")
            request_id: Unique request identifier
            user_id: User identifier
            model_id: Model identifier if applicable
            provider_name: Provider name if applicable
            status_code: HTTP status code
            response_data: Response data for summary
            processing_time_ms: Processing time in milliseconds
            token_usage: Token usage information
            additional_data: Additional data to include in log
        """
        log_extra = {
            "log_type": "response",
            "request_id": request_id,
            "user_id": user_id,
            "http_status_code": status_code
        }
        
        if model_id:
            log_extra["model_id"] = model_id
        if provider_name:
            log_extra["provider_name"] = provider_name
        if processing_time_ms:
            log_extra["processing_time_ms"] = processing_time_ms
            
        # Create response body summary
        response_summary = {}
        if response_data:
            if "data" in response_data:
                response_summary["data_length"] = len(response_data["data"])
            if "choices" in response_data:
                response_summary["choices_count"] = len(response_data["choices"])
            if "usage" in response_data:
                usage = response_data["usage"]
                response_summary["prompt_tokens"] = usage.get("prompt_tokens", 0)
                response_summary["completion_tokens"] = usage.get("completion_tokens", 0)
                response_summary["total_tokens"] = usage.get("total_tokens", 0)
            if "object" in response_data:
                response_summary["object_type"] = response_data["object"]
        
        log_extra["response_body_summary"] = response_summary
        
        # Add token usage if provided separately
        if token_usage:
            log_extra.update(token_usage)
        
        if additional_data:
            log_extra.update(additional_data)
        
        logger.info(operation, extra=log_extra)


class DebugLogger:
    """Centralized debug logging utility with lazy evaluation."""
    
    @staticmethod
    def log_data_flow(
        logger: logging.Logger,
        title: str,
        data: Union[Dict[str, Any], Callable[[], Dict[str, Any]]],
        data_flow: str,
        component: str,
        request_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log data flow for debugging with lazy evaluation.
        
        Args:
            logger: Logger instance to use
            title: Log title (e.g., "DEBUG: Request JSON")
            data: Data to log or callable that returns data
            data_flow: Data flow direction (incoming/outgoing)
            component: Component name
            request_id: Request identifier
            additional_data: Additional data to include in log
        """
        # Handle both raw logging.Logger and our Logger wrapper
        if hasattr(logger, 'isEnabledFor'):
            # Raw logging.Logger or mock with isEnabledFor
            if not logger.isEnabledFor(logging.DEBUG):
                return  # Skip entirely if debug is disabled
        elif hasattr(logger, 'logger'):
            # Our Logger wrapper - check the underlying logger
            if not logger.logger.isEnabledFor(logging.DEBUG):
                return  # Skip entirely if debug is disabled
        else:
            # Unknown logger type - assume debug is disabled for safety
            return
        
        # Lazy evaluation of data if callable
        debug_data = data() if callable(data) else data
        
        log_extra = {
            "debug_json_data": debug_data,
            "debug_data_flow": data_flow,
            "debug_component": component,
            "request_id": request_id
        }
        
        if additional_data:
            log_extra.update(additional_data)
        
        logger.debug(title, extra=log_extra)
    
    @staticmethod
    def log_provider_request(
        logger: logging.Logger,
        provider_name: str,
        url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        request_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log provider request for debugging."""
        # Handle both raw logging.Logger and our Logger wrapper
        if hasattr(logger, 'isEnabledFor'):
            # Raw logging.Logger or mock with isEnabledFor
            if not logger.isEnabledFor(logging.DEBUG):
                return
        elif hasattr(logger, 'logger'):
            # Our Logger wrapper - check the underlying logger
            if not logger.logger.isEnabledFor(logging.DEBUG):
                return
        else:
            # Unknown logger type - assume debug is disabled for safety
            return
        
        DebugLogger.log_data_flow(
            logger=logger,
            title=f"DEBUG: {provider_name.title()} Request",
            data={
                "url": url,
                "headers": headers,
                "request_body": request_body
            },
            data_flow="to_provider",
            component=f"{provider_name}_provider",
            request_id=request_id,
            additional_data=additional_data
        )
    
    @staticmethod
    def log_provider_response(
        logger: logging.Logger,
        provider_name: str,
        response_data: Union[Dict[str, Any], Callable[[], Dict[str, Any]]],
        request_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log provider response for debugging."""
        # Handle both raw logging.Logger and our Logger wrapper
        if hasattr(logger, 'isEnabledFor'):
            # Raw logging.Logger or mock with isEnabledFor
            if not logger.isEnabledFor(logging.DEBUG):
                return
        elif hasattr(logger, 'logger'):
            # Our Logger wrapper - check the underlying logger
            if not logger.logger.isEnabledFor(logging.DEBUG):
                return
        else:
            # Unknown logger type - assume debug is disabled for safety
            return
        
        DebugLogger.log_data_flow(
            logger=logger,
            title=f"DEBUG: {provider_name.title()} Response",
            data=response_data,
            data_flow="from_provider",
            component=f"{provider_name}_provider",
            request_id=request_id,
            additional_data=additional_data
        )


class PerformanceLogger:
    """Centralized performance logging utility."""
    
    @staticmethod
    def log_operation_timing(
        logger: logging.Logger,
        operation: str,
        start_time: float,
        request_id: str,
        user_id: str,
        model_id: Optional[str] = None,
        additional_metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Log operation timing and performance metrics.
        
        Args:
            logger: Logger instance to use
            operation: Operation name
            start_time: Start time (time.time() result)
            request_id: Request identifier
            user_id: User identifier
            model_id: Model identifier if applicable
            additional_metrics: Additional performance metrics
        """
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        log_extra = {
            "log_type": "performance",
            "operation": operation,
            "request_id": request_id,
            "user_id": user_id,
            "duration_ms": duration_ms,
            "start_time": start_time,
            "end_time": end_time
        }
        
        if model_id:
            log_extra["model_id"] = model_id
        
        if additional_metrics:
            log_extra.update(additional_metrics)
        
        logger.info(f"Performance: {operation}", extra=log_extra)
    
    @staticmethod
    def create_timing_context(operation: str, request_id: str, user_id: str, model_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a timing context for performance measurement."""
        return {
            "operation": operation,
            "start_time": time.time(),
            "request_id": request_id,
            "user_id": user_id,
            "model_id": model_id
        }
    
    @staticmethod
    def complete_timing_context(
        logger: logging.Logger,
        context: Dict[str, Any],
        additional_metrics: Optional[Dict[str, Any]] = None
    ):
        """Complete a timing context and log the performance metrics."""
        PerformanceLogger.log_operation_timing(
            logger=logger,
            operation=context["operation"],
            start_time=context["start_time"],
            request_id=context["request_id"],
            user_id=context["user_id"],
            model_id=context.get("model_id"),
            additional_metrics=additional_metrics
        )
    
    @staticmethod
    @contextmanager
    def timing_context(
        logger: logging.Logger,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: Optional[str] = None,
        additional_metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager for automatic timing measurement.
        
        Example usage:
        ```python
        with PerformanceLogger.timing_context(
            logger=logger,
            operation="Chat Completion",
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        ):
            # ... perform operation ...
            result = provider.chat_completions(...)
        ```
        """
        start_time = time.time()
        try:
            yield
        finally:
            PerformanceLogger.log_operation_timing(
                logger=logger,
                operation=operation,
                start_time=start_time,
                request_id=request_id,
                user_id=user_id,
                model_id=model_id,
                additional_metrics=additional_metrics
            )


class StreamingLogger:
    """Centralized streaming response logging utility."""
    
    @staticmethod
    def log_streaming_start(
        logger: logging.Logger,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log the start of a streaming response."""
        log_extra = {
            "log_type": "streaming_start",
            "request_id": request_id,
            "user_id": user_id,
            "model_id": model_id,
            "response_type": "streaming"
        }
        
        if additional_data:
            log_extra.update(additional_data)
        
        logger.info(f"Initiating {operation}", extra=log_extra)
    
    @staticmethod
    def log_streaming_end(
        logger: logging.Logger,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: str,
        chunk_count: int,
        processing_time_ms: int,
        token_usage: Optional[Dict[str, int]] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """Log the end of a streaming response."""
        log_extra = {
            "log_type": "streaming_end",
            "request_id": request_id,
            "user_id": user_id,
            "model_id": model_id,
            "chunk_count": chunk_count,
            "processing_time_ms": processing_time_ms
        }
        
        if token_usage:
            log_extra.update(token_usage)
        
        if additional_data:
            log_extra.update(additional_data)
        
        logger.info(f"Completed {operation}", extra=log_extra)
    
    @staticmethod
    def log_streaming_chunk(
        logger: logging.Logger,
        chunk_data: Dict[str, Any],
        request_id: str,
        user_id: str,
        model_id: str,
        chunk_number: int
    ):
        """Log a streaming chunk (debug level only)."""
        # Handle both raw logging.Logger and our Logger wrapper
        if hasattr(logger, 'isEnabledFor'):
            # Raw logging.Logger or mock with isEnabledFor
            if not logger.isEnabledFor(logging.DEBUG):
                return
        elif hasattr(logger, 'logger'):
            # Our Logger wrapper - check the underlying logger
            if not logger.logger.isEnabledFor(logging.DEBUG):
                return
        else:
            # Unknown logger type - assume debug is disabled for safety
            return
        
        log_extra = {
            "log_type": "streaming_chunk",
            "request_id": request_id,
            "user_id": user_id,
            "model_id": model_id,
            "chunk_number": chunk_number,
            "chunk_size": len(str(chunk_data))
        }
        
        logger.debug(f"Streaming chunk {chunk_number}", extra=log_extra)