"""Unit tests for the error handling system (ErrorType, ErrorContext, ErrorHandler)."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
import httpx

from src.core.error_handling.error_types import ErrorType, ErrorContext
from src.core.error_handling.error_handler import ErrorHandler


# ---------------------------------------------------------------------------
# ErrorType enum
# ---------------------------------------------------------------------------

class TestErrorTypeEnumValues:
    """Verify each enum member carries the correct (code, status_code, template)."""

    @pytest.mark.parametrize(
        "member, expected_code, expected_status, expected_template",
        [
            (ErrorType.MODEL_NOT_SPECIFIED, "model_not_specified", 400, "Model not specified in request"),
            (ErrorType.MISSING_REQUIRED_FIELD, "missing_required_field", 400, "Missing required field: {field_name}"),
            (ErrorType.MISSING_API_KEY, "missing_api_key", 401, "API key missing"),
            (ErrorType.INVALID_API_KEY, "invalid_api_key", 401, "Invalid API key"),
            (ErrorType.MODEL_NOT_ALLOWED, "model_not_allowed", 403, "Model '{model_id}' is not available for your account"),
            (ErrorType.ENDPOINT_NOT_ALLOWED, "endpoint_not_allowed", 403, "Access to endpoint '{endpoint_path}' is not allowed"),
            (ErrorType.MODEL_NOT_FOUND, "model_not_found", 404, "Model '{model_id}' not found in configuration"),
            (ErrorType.PROVIDER_NOT_FOUND, "provider_not_found", 404, "Provider '{provider_name}' not found for model '{model_id}'"),
            (ErrorType.PROVIDER_CONFIG_ERROR, "provider_config_error", 500, "Provider configuration error: {error_details}"),
            (ErrorType.INTERNAL_SERVER_ERROR, "internal_server_error", 500, "Internal server error: {error_details}"),
            (ErrorType.PROVIDER_NETWORK_ERROR, "provider_network_error", 500, "Network error communicating with provider: {error_details}"),
            (ErrorType.SERVICE_UNAVAILABLE, "service_unavailable", 503, "Could not connect to service: {error_details}"),
        ],
    )
    def test_enum_member_attributes(self, member, expected_code, expected_status, expected_template):
        assert member.code == expected_code
        assert member.status_code == expected_status
        assert member.message_template == expected_template


class TestErrorTypeFormatMessage:
    def test_format_message_with_valid_kwargs(self):
        msg = ErrorType.MODEL_NOT_FOUND.format_message(model_id="gpt-4")
        assert msg == "Model 'gpt-4' not found in configuration"

    def test_format_message_with_multiple_kwargs(self):
        msg = ErrorType.PROVIDER_NOT_FOUND.format_message(
            provider_name="openai", model_id="gpt-4"
        )
        assert msg == "Provider 'openai' not found for model 'gpt-4'"

    def test_format_message_missing_kwargs_returns_raw_template(self):
        msg = ErrorType.MODEL_NOT_FOUND.format_message()
        assert msg == ErrorType.MODEL_NOT_FOUND.message_template

    def test_format_message_no_placeholders(self):
        msg = ErrorType.MODEL_NOT_SPECIFIED.format_message()
        assert msg == "Model not specified in request"


class TestErrorTypeCreateErrorDetail:
    def test_returns_correct_structure(self):
        detail = ErrorType.MODEL_NOT_SPECIFIED.create_error_detail()
        assert "error" in detail
        assert detail["error"]["code"] == 400
        assert detail["error"]["message"] == "Model not specified in request"

    def test_includes_formatted_message(self):
        detail = ErrorType.MODEL_NOT_FOUND.create_error_detail(model_id="gpt-4")
        assert detail["error"]["message"] == "Model 'gpt-4' not found in configuration"

    def test_includes_metadata_when_provider_name_given(self):
        detail = ErrorType.PROVIDER_NOT_FOUND.create_error_detail(
            provider_name="openai", model_id="gpt-4"
        )
        assert "metadata" in detail["error"]
        assert detail["error"]["metadata"]["provider_name"] == "openai"

    def test_omits_metadata_when_provider_name_absent(self):
        detail = ErrorType.MODEL_NOT_FOUND.create_error_detail(model_id="gpt-4")
        assert "metadata" not in detail["error"]

    def test_omits_metadata_when_provider_name_is_none(self):
        detail = ErrorType.MODEL_NOT_FOUND.create_error_detail(
            model_id="gpt-4", provider_name=None
        )
        assert "metadata" not in detail["error"]


# ---------------------------------------------------------------------------
# ErrorContext
# ---------------------------------------------------------------------------

class TestErrorContext:
    def test_to_log_extra_always_includes_log_type(self):
        ctx = ErrorContext()
        extra = ctx.to_log_extra()
        assert extra["log_type"] == "error"

    def test_to_log_extra_includes_only_non_none_fields(self):
        ctx = ErrorContext(request_id="req-1", model_id="gpt-4")
        extra = ctx.to_log_extra()
        assert extra["request_id"] == "req-1"
        assert extra["model_id"] == "gpt-4"
        assert "user_id" not in extra
        assert "endpoint_path" not in extra
        assert "provider_name" not in extra

    def test_to_log_extra_includes_all_set_fields(self):
        ctx = ErrorContext(
            request_id="r1",
            user_id="u1",
            model_id="m1",
            endpoint_path="/v1/chat",
            provider_name="openai",
        )
        extra = ctx.to_log_extra()
        assert extra["request_id"] == "r1"
        assert extra["user_id"] == "u1"
        assert extra["model_id"] == "m1"
        assert extra["endpoint_path"] == "/v1/chat"
        assert extra["provider_name"] == "openai"

    def test_additional_context_merged_into_extra(self):
        ctx = ErrorContext(request_id="r1", custom_field="custom_value")
        extra = ctx.to_log_extra()
        assert extra["custom_field"] == "custom_value"
        assert extra["request_id"] == "r1"

    def test_empty_context_returns_only_log_type(self):
        ctx = ErrorContext()
        extra = ctx.to_log_extra()
        assert extra == {"log_type": "error"}


# ---------------------------------------------------------------------------
# ErrorHandler
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_error_logger():
    with patch(
        "src.core.error_handling.error_handler.ErrorLogger.log_error"
    ) as mock_log:
        yield mock_log


@pytest.fixture
def context():
    return ErrorContext(request_id="test-req", user_id="test-user")


class TestErrorHandlerCreateHttpException:
    def test_returns_http_exception_with_correct_status(self, mock_error_logger):
        exc = ErrorHandler.create_http_exception(
            ErrorType.MODEL_NOT_SPECIFIED, context=ErrorContext()
        )
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 400

    def test_detail_contains_error_structure(self, mock_error_logger):
        exc = ErrorHandler.create_http_exception(
            ErrorType.MODEL_NOT_SPECIFIED, context=ErrorContext()
        )
        assert "error" in exc.detail
        assert exc.detail["error"]["code"] == 400

    def test_calls_error_logger(self, mock_error_logger):
        ErrorHandler.create_http_exception(
            ErrorType.MODEL_NOT_SPECIFIED, context=ErrorContext()
        )
        mock_error_logger.assert_called_once()

    def test_context_none_creates_default(self, mock_error_logger):
        exc = ErrorHandler.create_http_exception(
            ErrorType.MODEL_NOT_SPECIFIED, context=None
        )
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 400
        mock_error_logger.assert_called_once()


class TestErrorHandlerModelNotSpecified:
    def test_returns_400(self, mock_error_logger, context):
        exc = ErrorHandler.handle_model_not_specified(context)
        assert exc.status_code == 400
        assert "Model not specified" in exc.detail["error"]["message"]


class TestErrorHandlerModelNotAllowed:
    def test_returns_403_with_model_id(self, mock_error_logger, context):
        exc = ErrorHandler.handle_model_not_allowed("gpt-4", context)
        assert exc.status_code == 403
        assert "gpt-4" in exc.detail["error"]["message"]


class TestErrorHandlerModelNotFound:
    def test_returns_404_with_model_id(self, mock_error_logger, context):
        exc = ErrorHandler.handle_model_not_found("gpt-4", context)
        assert exc.status_code == 404
        assert "gpt-4" in exc.detail["error"]["message"]


class TestErrorHandlerProviderNotFound:
    def test_returns_404(self, mock_error_logger, context):
        exc = ErrorHandler.handle_provider_not_found("openai", "gpt-4", context)
        assert exc.status_code == 404
        assert "openai" in exc.detail["error"]["message"]
        assert "gpt-4" in exc.detail["error"]["message"]


class TestErrorHandlerProviderConfigError:
    def test_returns_500(self, mock_error_logger, context):
        exc = ErrorHandler.handle_provider_config_error("bad config", context)
        assert exc.status_code == 500
        assert "bad config" in exc.detail["error"]["message"]

    def test_passes_original_exception(self, mock_error_logger, context):
        orig = ValueError("original")
        ErrorHandler.handle_provider_config_error("bad config", context, original_exception=orig)
        call_kwargs = mock_error_logger.call_args[1]
        assert call_kwargs["original_exception"] is orig


class TestErrorHandlerProviderNetworkError:
    def test_returns_500(self, mock_error_logger, context):
        orig = httpx.ConnectError("connection refused")
        exc = ErrorHandler.handle_provider_network_error(orig, context, provider_name="openai")
        assert exc.status_code == 500
        assert "connection refused" in exc.detail["error"]["message"]


class TestErrorHandlerAuthErrors:
    def test_missing_api_key_returns_401(self, mock_error_logger, context):
        exc = ErrorHandler.handle_auth_errors("missing_api_key", context)
        assert exc.status_code == 401

    def test_invalid_api_key_returns_401(self, mock_error_logger, context):
        exc = ErrorHandler.handle_auth_errors("invalid_api_key", context)
        assert exc.status_code == 401

    def test_unknown_type_falls_back_to_500(self, mock_error_logger, context):
        exc = ErrorHandler.handle_auth_errors("unknown_type", context)
        assert exc.status_code == 500
        assert "unknown_type" in exc.detail["error"]["message"]


class TestErrorHandlerEndpointNotAllowed:
    def test_returns_403(self, mock_error_logger, context):
        exc = ErrorHandler.handle_endpoint_not_allowed("/v1/secret", context)
        assert exc.status_code == 403
        assert "/v1/secret" in exc.detail["error"]["message"]


class TestErrorHandlerServiceUnavailable:
    def test_returns_503(self, mock_error_logger, context):
        exc = ErrorHandler.handle_service_unavailable("redis down", context)
        assert exc.status_code == 503
        assert "redis down" in exc.detail["error"]["message"]
