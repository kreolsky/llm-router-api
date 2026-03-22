"""Request/response logging middleware with request ID injection."""
import time
import os
import json
from typing import Dict, Any
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from ..core.logging import logger


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Injects request_id into state and logs request/response lifecycle."""

    async def dispatch(self, request: Request, call_next):
        """Generate request_id, log lifecycle, and add X-Process-Time header."""
        start_time = time.time()
        request_id = os.urandom(8).hex()
        request.state.request_id = request_id

        user_id = request.state.project_name if hasattr(request.state, 'project_name') else "unknown"

        logger.info(
            f"Request: Incoming Request | method={request.method}",
            request_id=request_id,
            user_id=user_id,
            url=str(request.url)
        )
        
        if request.method in ["POST", "PUT", "PATCH"] and logger.is_debug_enabled():
            try:
                request_body = await request.json()
                logger.debug_data(
                    title="Request JSON",
                    data=request_body,
                    request_id=request_id,
                    component="middleware",
                    data_flow="incoming"
                )
            except Exception:
                logger.debug("Could not parse request JSON", request_id=request_id)

        try:
            response = await call_next(request)
        except HTTPException as e:
            detail = e.detail
            if isinstance(detail, dict):
                error_obj = detail.get('error', {})
                if isinstance(error_obj, dict):
                    message = error_obj.get('message', str(detail))
                    code = error_obj.get('code', 'unknown_error')
                else:
                    message = str(detail)
                    code = 'unknown_error'
            else:
                message = str(detail)
                code = 'unknown_error'

            logger.error(
                f"HTTP Exception: {message}",
                request_id=request_id,
                user_id=user_id,
                status_code=e.status_code,
                error_code=code
            )
            raise e
        except Exception as e:
            logger.error(
                f"Unexpected error: {str(e)}",
                request_id=request_id,
                user_id=user_id,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                exc_info=True
            )
            raise e

        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)

        logger.info(
            f"Response: Outgoing Response | status={response.status_code} | time={round(process_time * 1000)}ms",
            request_id=request_id,
            user_id=user_id
        )
        
        return response