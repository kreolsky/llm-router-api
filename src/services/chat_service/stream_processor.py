"""
Stream Processor Module

This module provides the StreamProcessor class for transparently forwarding
streaming responses from AI providers to clients without any processing
or modification.

The StreamProcessor implements complete transparent proxying, ensuring that
all provider responses are passed through exactly as received.
"""

import json
from typing import Dict, Any, AsyncGenerator

from src.logging.config import logger
from src.core.exceptions import ProviderStreamError, ProviderNetworkError


class StreamProcessor:
    """
    Transparent stream processor that forwards provider responses without modification.
    
    This processor implements complete transparent proxying, ensuring that all
    provider responses are passed through exactly as received without any
    processing, filtering, or transformation.
    
    Key Features:
    - Complete transparency: Passes through all provider responses unchanged
    - Zero processing overhead: Direct pass-through with minimal intervention
    - Error handling: Properly formats errors while maintaining transparency
    - Simple and reliable: Minimal code for maximum reliability
    """
    
    def __init__(self):
        """Initialize StreamProcessor for transparent proxying."""
        # No initialization needed for transparent proxying
        pass
    
    async def process_stream(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           model_id: str,
                           request_id: str,
                           user_id: str) -> AsyncGenerator[bytes, None]:
        """
        Completely transparent stream processing - just pass through everything.
        
        Args:
            provider_stream: Raw byte stream from the provider
            model_id: ID of the model being used for the request
            request_id: Unique identifier for the request for logging and tracking
            user_id: Identifier for the user making the request
            
        Yields:
            bytes: Raw chunks from the provider, passed through unchanged
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
    
    def _format_error(self, error: Exception) -> bytes:
        """
        Formats an error in SSE format for transparent error forwarding.
        
        Args:
            error: Exception to format
            
        Returns:
            bytes: Formatted error chunk in SSE format
        """
        if isinstance(error, ProviderStreamError):
            message = error.message
            code = error.error_code
        elif isinstance(error, ProviderNetworkError):
            message = error.message
            code = "provider_network_error"
        else:
            message = f"An unexpected error occurred during streaming: {error}"
            code = "unexpected_streaming_error"
        
        error_payload = {
            "error": {
                "message": message,
                "type": "api_error",
                "code": code,
                "param": None
            }
        }
        
        return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')