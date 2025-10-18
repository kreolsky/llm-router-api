"""
Main Logger class that provides centralized logging functionality.

This module contains the main Logger class that serves as a centralized interface
for all logging operations, providing a single point of control for logging
configuration and usage throughout the application.
"""

import logging
from typing import Optional, Dict, Any
from .config import setup_logging
from .utils import RequestLogger, DebugLogger, PerformanceLogger, StreamingLogger


class Logger:
    """
    Main Logger class that provides centralized logging functionality.
    
    This class serves as a facade for all logging operations, providing a unified
    interface while maintaining backward compatibility with existing log formats.
    """
    
    def __init__(self, logger_instance: Optional[logging.Logger] = None):
        """
        Initialize the Logger with an optional custom logger instance.
        
        Args:
            logger_instance: Optional custom logger instance. If None, uses the default logger.
        """
        self._logger = logger_instance or setup_logging()
        self.request_logger = RequestLogger()
        self.debug_logger = DebugLogger()
        self.performance_logger = PerformanceLogger()
        self.streaming_logger = StreamingLogger()
    
    @property
    def logger(self) -> logging.Logger:
        """Get the underlying logger instance."""
        return self._logger
    
    def is_debug_enabled(self) -> bool:
        """Check if debug logging is enabled."""
        return self._logger.isEnabledFor(logging.DEBUG)
    
    def info(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log an info message."""
        if extra:
            self._logger.info(message, extra=extra)
        else:
            self._logger.info(message)
    
    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log a debug message."""
        if extra:
            self._logger.debug(message, extra=extra)
        else:
            self._logger.debug(message)
    
    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log a warning message."""
        if extra:
            self._logger.warning(message, extra=extra)
        else:
            self._logger.warning(message)
    
    def error(self, message: str, extra: Optional[Dict[str, Any]] = None, exc_info: bool = False):
        """Log an error message."""
        if extra:
            self._logger.error(message, extra=extra, exc_info=exc_info)
        else:
            self._logger.error(message, exc_info=exc_info)
    
    def critical(self, message: str, extra: Optional[Dict[str, Any]] = None):
        """Log a critical message."""
        if extra:
            self._logger.critical(message, extra=extra)
        else:
            self._logger.critical(message)
    
    def log_request(
        self,
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
        
        This is a convenience method that delegates to RequestLogger.log_request.
        """
        self.request_logger.log_request(
            logger=self._logger,
            operation=operation,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            provider_name=provider_name,
            request_data=request_data,
            additional_data=additional_data
        )
    
    def log_response(
        self,
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
        
        This is a convenience method that delegates to RequestLogger.log_response.
        """
        self.request_logger.log_response(
            logger=self._logger,
            operation=operation,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            provider_name=provider_name,
            status_code=status_code,
            response_data=response_data,
            processing_time_ms=processing_time_ms,
            token_usage=token_usage,
            additional_data=additional_data
        )
    
    def log_debug_data(
        self,
        title: str,
        data: Any,
        data_flow: str,
        component: str,
        request_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log data flow for debugging.
        
        This is a convenience method that delegates to DebugLogger.log_data_flow.
        """
        self.debug_logger.log_data_flow(
            logger=self._logger,
            title=title,
            data=data,
            data_flow=data_flow,
            component=component,
            request_id=request_id,
            additional_data=additional_data
        )
    
    def log_provider_request(
        self,
        provider_name: str,
        url: str,
        headers: Dict[str, str],
        request_body: Dict[str, Any],
        request_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log provider request for debugging.
        
        This is a convenience method that delegates to DebugLogger.log_provider_request.
        """
        self.debug_logger.log_provider_request(
            logger=self._logger,
            provider_name=provider_name,
            url=url,
            headers=headers,
            request_body=request_body,
            request_id=request_id,
            additional_data=additional_data
        )
    
    def log_provider_response(
        self,
        provider_name: str,
        response_data: Any,
        request_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log provider response for debugging.
        
        This is a convenience method that delegates to DebugLogger.log_provider_response.
        """
        self.debug_logger.log_provider_response(
            logger=self._logger,
            provider_name=provider_name,
            response_data=response_data,
            request_id=request_id,
            additional_data=additional_data
        )
    
    def log_performance(
        self,
        operation: str,
        start_time: float,
        request_id: str,
        user_id: str,
        model_id: Optional[str] = None,
        additional_metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Log operation timing and performance metrics.
        
        This is a convenience method that delegates to PerformanceLogger.log_operation_timing.
        """
        self.performance_logger.log_operation_timing(
            logger=self._logger,
            operation=operation,
            start_time=start_time,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            additional_metrics=additional_metrics
        )
    
    def create_timing_context(
        self,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a timing context for performance measurement.
        
        This is a convenience method that delegates to PerformanceLogger.create_timing_context.
        """
        return self.performance_logger.create_timing_context(
            operation=operation,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id
        )
    
    def complete_timing_context(
        self,
        context: Dict[str, Any],
        additional_metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Complete a timing context and log the performance metrics.
        
        This is a convenience method that delegates to PerformanceLogger.complete_timing_context.
        """
        self.performance_logger.complete_timing_context(
            logger=self._logger,
            context=context,
            additional_metrics=additional_metrics
        )
    
    def timing_context(
        self,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: Optional[str] = None,
        additional_metrics: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager for automatic timing measurement.
        
        This is a convenience method that delegates to PerformanceLogger.timing_context.
        """
        return self.performance_logger.timing_context(
            logger=self._logger,
            operation=operation,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            additional_metrics=additional_metrics
        )
    
    def log_streaming_start(
        self,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: str,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log the start of a streaming response.
        
        This is a convenience method that delegates to StreamingLogger.log_streaming_start.
        """
        self.streaming_logger.log_streaming_start(
            logger=self._logger,
            operation=operation,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            additional_data=additional_data
        )
    
    def log_streaming_end(
        self,
        operation: str,
        request_id: str,
        user_id: str,
        model_id: str,
        chunk_count: int,
        processing_time_ms: int,
        token_usage: Optional[Dict[str, int]] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log the end of a streaming response.
        
        This is a convenience method that delegates to StreamingLogger.log_streaming_end.
        """
        self.streaming_logger.log_streaming_end(
            logger=self._logger,
            operation=operation,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            chunk_count=chunk_count,
            processing_time_ms=processing_time_ms,
            token_usage=token_usage,
            additional_data=additional_data
        )
    
    def log_streaming_chunk(
        self,
        chunk_data: Dict[str, Any],
        request_id: str,
        user_id: str,
        model_id: str,
        chunk_number: int
    ):
        """
        Log a streaming chunk (debug level only).
        
        This is a convenience method that delegates to StreamingLogger.log_streaming_chunk.
        """
        self.streaming_logger.log_streaming_chunk(
            logger=self._logger,
            chunk_data=chunk_data,
            request_id=request_id,
            user_id=user_id,
            model_id=model_id,
            chunk_number=chunk_number
        )


# Create a default logger instance for easy import
default_app_logger = Logger()