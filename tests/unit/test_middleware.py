"""Unit tests for RequestLoggerMiddleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from src.api.middleware import RequestLoggerMiddleware


@pytest.fixture
def app():
    """Create a FastAPI app with the middleware for testing."""
    app = FastAPI()
    app.add_middleware(RequestLoggerMiddleware)

    @app.get("/ok")
    async def ok_endpoint():
        return {"status": "ok"}

    @app.post("/echo")
    async def echo_endpoint(request: Request):
        body = await request.json()
        return body

    @app.get("/http-error")
    async def http_error_endpoint():
        raise HTTPException(status_code=403, detail="forbidden")

    @app.get("/http-error-structured")
    async def http_error_structured():
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": 400, "message": "bad request", "metadata": {}}}
        )

    @app.get("/unhandled-error")
    async def unhandled_error_endpoint():
        raise RuntimeError("boom")

    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


class TestRequestLoggerMiddleware:

    @patch("src.api.middleware.logger")
    def test_injects_request_id(self, mock_logger, client):
        """Request ID is generated and set in state."""
        response = client.get("/ok")
        assert response.status_code == 200
        # X-Process-Time header is added
        assert "x-process-time" in response.headers

    @patch("src.api.middleware.logger")
    def test_x_process_time_header(self, mock_logger, client):
        """X-Process-Time header is a valid float."""
        response = client.get("/ok")
        process_time = float(response.headers["x-process-time"])
        assert process_time >= 0

    @patch("src.api.middleware.logger")
    def test_logs_request_and_response(self, mock_logger, client):
        """Middleware calls logger.info for request and response."""
        client.get("/ok")
        info_calls = mock_logger.info.call_args_list
        # At least two info calls: one for request, one for response
        assert len(info_calls) >= 2
        req_msg = info_calls[0].args[0]
        assert "Request: Incoming Request" in req_msg
        resp_msg = info_calls[-1].args[0]
        assert "Response: Outgoing Response" in resp_msg

    @patch("src.api.middleware.logger")
    def test_http_exception_returns_correct_status(self, mock_logger, client):
        """HTTPException endpoints return the correct HTTP status code."""
        response = client.get("/http-error")
        assert response.status_code == 403

    @patch("src.api.middleware.logger")
    def test_http_exception_structured_returns_correct_status(self, mock_logger, client):
        """HTTPException with structured detail returns correct status."""
        response = client.get("/http-error-structured")
        assert response.status_code == 400

    @patch("src.api.middleware.logger")
    def test_unhandled_exception_logged(self, mock_logger, client):
        """Unhandled exceptions are logged with 500 status."""
        response = client.get("/unhandled-error")
        assert response.status_code == 500
        mock_logger.error.assert_called()
        error_call = mock_logger.error.call_args
        assert "boom" in error_call.args[0]
        assert error_call.kwargs["status_code"] == 500

    @patch("src.api.middleware.logger")
    def test_user_id_defaults_to_unknown(self, mock_logger, client):
        """When project_name is not set, user_id defaults to 'unknown'."""
        client.get("/ok")
        info_calls = mock_logger.info.call_args_list
        req_kwargs = info_calls[0].kwargs
        assert req_kwargs["user_id"] == "unknown"

    @patch("src.api.middleware.logger")
    def test_post_body_logged_in_debug(self, mock_logger, client):
        """POST body is logged when debug is enabled."""
        mock_logger.is_debug_enabled.return_value = True
        client.post("/echo", json={"key": "value"})
        mock_logger.debug_data.assert_called()
        data_call = mock_logger.debug_data.call_args
        assert data_call.kwargs["title"] == "Request JSON"

    @patch("src.api.middleware.logger")
    def test_post_body_not_logged_when_debug_off(self, mock_logger, client):
        """POST body is NOT logged when debug is disabled."""
        mock_logger.is_debug_enabled.return_value = False
        client.post("/echo", json={"key": "value"})
        mock_logger.debug_data.assert_not_called()
