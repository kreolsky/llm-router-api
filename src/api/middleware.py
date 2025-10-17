import time
import os
import json
import logging
from typing import Dict, Any
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from ..core.logging import RequestLogger, DebugLogger, logger, std_logger

class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = os.urandom(8).hex() # Simple request ID
        request.state.request_id = request_id # Store request_id in request.state

        # Prepare common extra data for logging
        extra_data = {
            "request_id": request_id,
            "method": request.method,
            "url": str(request.url),
            "log_type": "request",
        }
        if hasattr(request.state, 'project_name'):
            extra_data["user_id"] = request.state.project_name

        # Log incoming request using centralized utility
        user_id = request.state.project_name if hasattr(request.state, 'project_name') else "unknown"
        RequestLogger.log_request(
            logger=std_logger,
            operation="Incoming Request",
            request_id=request_id,
            user_id=user_id,
            additional_data={
                "method": request.method,
                "url": str(request.url)
            }
        )
        
        # DEBUG logging of incoming request JSON using centralized utility
        if request.method in ["POST", "PUT", "PATCH"]:
            # Use lazy evaluation with a callable to avoid unnecessary JSON parsing
            DebugLogger.log_data_flow(
                logger=std_logger,
                title="DEBUG: Incoming Request JSON",
                data=lambda: self._get_request_body(request),
                data_flow="incoming",
                component="middleware",
                request_id=request_id
            )

        try:
            response = await call_next(request)
        except HTTPException as e:
            # Log HTTPExceptions
            user_id = request.state.project_name if hasattr(request.state, 'project_name') else "unknown"
            error_extra_data = {
                "request_id": request_id,
                "log_type": "error",
                "error_message": e.detail.get("error", {}).get("message", str(e.detail)),
                "error_code": e.detail.get("error", {}).get("code", "unknown_error"),
                "http_status_code": e.status_code,
                "user_id": user_id
            }
            std_logger.error(
                "Request processing failed with HTTPException",
                extra=error_extra_data,
                exc_info=True # Include stack trace for debugging
            )
            raise e
        except Exception as e:
            # Log other unexpected exceptions
            user_id = request.state.project_name if hasattr(request.state, 'project_name') else "unknown"
            error_extra_data = {
                "request_id": request_id,
                "log_type": "error",
                "error_message": str(e),
                "error_code": "unexpected_error",
                "http_status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "user_id": user_id
            }
            std_logger.error(
                "Request processing failed with unexpected error",
                extra=error_extra_data,
                exc_info=True
            )
            raise e

        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)

        # Log outgoing response using centralized utility
        user_id = request.state.project_name if hasattr(request.state, 'project_name') else "unknown"
        RequestLogger.log_response(
            logger=std_logger,
            operation="Outgoing Response",
            request_id=request_id,
            user_id=user_id,
            status_code=response.status_code,
            processing_time_ms=round(process_time * 1000)
        )
        
        # DEBUG logging of outgoing response JSON using centralized utility
        # Note: This is limited as response body might already be consumed
        # For full response logging, it's better to log at the service level
        if hasattr(response, 'body') and response.body:
            # Use lazy evaluation with a callable to avoid unnecessary processing
            DebugLogger.log_data_flow(
                logger=std_logger,
                title="DEBUG: Outgoing Response JSON",
                data=lambda: self._get_response_body(response),
                data_flow="outgoing",
                component="middleware",
                request_id=request_id
            )
        
        return response
    
    async def _get_request_body(self, request: Request) -> Dict[str, Any]:
        """Helper method to safely extract request body for debug logging."""
        try:
            # Clone the request to read body without consuming it
            return await request.json()
        except Exception:
            # If not JSON or can't read, return empty dict
            return {}
    
    def _get_response_body(self, response) -> Dict[str, Any]:
        """Helper method to safely extract response body for debug logging."""
        try:
            if isinstance(response.body, bytes):
                response_body_str = response.body.decode('utf-8')
                return json.loads(response_body_str)
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            # If not JSON or can't decode, return empty dict
            return {}
