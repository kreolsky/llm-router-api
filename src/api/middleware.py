import time
import os
import json
import logging
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("nnp-llm-router")

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

        # Log incoming request
        logger.info(
            "Incoming Request",
            extra=extra_data
        )
        
        # DEBUG logging of incoming request JSON
        if logger.isEnabledFor(logging.DEBUG) and request.method in ["POST", "PUT", "PATCH"]:
            request_body = None
            try:
                # Clone the request to read body without consuming it
                request_body = await request.json()
            except Exception:
                # If not JSON or can't read, skip debug logging
                pass
                
            if request_body:
                logger.debug(
                    "DEBUG: Incoming Request JSON",
                    extra={
                        "debug_json_data": request_body,
                        "debug_data_flow": "incoming",
                        "debug_component": "middleware",
                        "request_id": request_id
                    }
                )

        try:
            response = await call_next(request)
        except HTTPException as e:
            # Log HTTPExceptions
            error_extra_data = {
                "request_id": request_id,
                "log_type": "error",
                "error_message": e.detail.get("error", {}).get("message", str(e.detail)),
                "error_code": e.detail.get("error", {}).get("code", "unknown_error"),
                "http_status_code": e.status_code,
            }
            if hasattr(request.state, 'project_name'):
                error_extra_data["user_id"] = request.state.project_name
            logger.error(
                "Request processing failed with HTTPException",
                extra=error_extra_data,
                exc_info=True # Include stack trace for debugging
            )
            raise e
        except Exception as e:
            # Log other unexpected exceptions
            error_extra_data = {
                "request_id": request_id,
                "log_type": "error",
                "error_message": str(e),
                "error_code": "unexpected_error",
                "http_status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            }
            if hasattr(request.state, 'project_name'):
                error_extra_data["user_id"] = request.state.project_name
            logger.error(
                "Request processing failed with unexpected error",
                extra=error_extra_data,
                exc_info=True
            )
            raise e

        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)

        # Log outgoing response
        response_extra_data = {
            "request_id": request_id,
            "log_type": "response",
            "http_status_code": response.status_code,
            "process_time_ms": round(process_time * 1000),
        }
        if hasattr(request.state, 'project_name'):
            response_extra_data["user_id"] = request.state.project_name
        
        logger.info(
            "Outgoing Response",
            extra=response_extra_data
        )
        
        # DEBUG logging of outgoing response JSON
        # Note: This is limited as response body might already be consumed
        # For full response logging, it's better to log at the service level
        if logger.isEnabledFor(logging.DEBUG) and hasattr(response, 'body') and response.body:
            try:
                if isinstance(response.body, bytes):
                    response_body_str = response.body.decode('utf-8')
                    response_body = json.loads(response_body_str)
                    logger.debug(
                        "DEBUG: Outgoing Response JSON",
                        extra={
                            "debug_json_data": response_body,
                            "debug_data_flow": "outgoing",
                            "debug_component": "middleware",
                            "request_id": request_id
                        }
                    )
            except (json.JSONDecodeError, UnicodeDecodeError):
                # If not JSON, skip debug logging
                pass
        
        return response
