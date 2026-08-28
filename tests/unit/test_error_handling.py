"""Unit tests for the error handling system (ErrorType, create_error)."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.core.error_handling.error_handler import create_error
from src.core.error_handling.error_types import ErrorType

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

    def test_format_message_missing_kwargs_strips_placeholder_tokens(self):
        """A missing kwarg must not leak the raw `{...}` token to the client.

        metadata.error_code is the machine-read field; the message is
        human-only prose.
        """
        msg = ErrorType.SERVICE_UNAVAILABLE.format_message()
        assert msg == "Could not connect to service: "
        assert "{" not in msg

    def test_format_message_missing_kwarg_keeps_surrounding_text(self):
        msg = ErrorType.MODEL_NOT_FOUND.format_message()
        assert msg == "Model '' not found in configuration"

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

    def test_always_includes_metadata_error_code(self):
        """metadata.error_code is always emitted (string classification).

        WHY: the numeric error.code carries the HTTP status; consumers that
        need the error class (stats enrichment among them) read
        metadata.error_code.
        """
        detail = ErrorType.INVALID_API_KEY.create_error_detail()
        assert detail["error"]["metadata"]["error_code"] == "invalid_api_key"

    def test_includes_provider_name_in_metadata_when_given(self):
        detail = ErrorType.PROVIDER_NOT_FOUND.create_error_detail(
            provider_name="openai", model_id="gpt-4"
        )
        assert detail["error"]["metadata"]["provider_name"] == "openai"
        assert detail["error"]["metadata"]["error_code"] == "provider_not_found"

    def test_metadata_without_provider_name_still_present(self):
        """No provider_name: metadata exists but carries no provider_name."""
        detail = ErrorType.MODEL_NOT_FOUND.create_error_detail(model_id="gpt-4")
        assert "metadata" in detail["error"]
        assert "provider_name" not in detail["error"]["metadata"]

    def test_metadata_when_provider_name_is_none(self):
        detail = ErrorType.MODEL_NOT_FOUND.create_error_detail(
            model_id="gpt-4", provider_name=None
        )
        assert "provider_name" not in detail["error"]["metadata"]


# ---------------------------------------------------------------------------
# create_error
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_logger():
    with patch("src.core.error_handling.error_handler.logger") as mock_log:
        yield mock_log


class TestCreateProviderHttpError:
    """create_provider_http_error must carry its own metadata.error_code."""

    def test_metadata_contains_provider_http_error_code(self, mock_logger):
        from src.core.error_handling.error_handler import create_provider_http_error

        exc = create_provider_http_error(
            status_code=429, message="rate limited",
            provider_name="openai", raw="upstream said no",
        )
        assert exc.status_code == 429
        assert exc.detail["error"]["metadata"]["error_code"] == "provider_http_error"
        assert exc.detail["error"]["metadata"]["provider_name"] == "openai"
        assert exc.detail["error"]["metadata"]["raw"] == "upstream said no"


class TestCreateError:
    def test_returns_http_exception_with_correct_status(self, mock_logger):
        exc = create_error(ErrorType.MODEL_NOT_SPECIFIED)
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 400

    def test_detail_contains_error_structure(self, mock_logger):
        exc = create_error(ErrorType.MODEL_NOT_SPECIFIED)
        assert "error" in exc.detail
        assert exc.detail["error"]["code"] == 400

    def test_4xx_logs_warning_not_error(self, mock_logger):
        """4xx is a client error: WARNING, and log_type "warning" — auth already
        logged its own WARNING line; a second line at ERROR doubled every 401/403."""
        create_error(ErrorType.INVALID_API_KEY)
        mock_logger.error.assert_not_called()
        call_kwargs = mock_logger.warning.call_args
        assert call_kwargs[1]["extra"]["log_type"] == "warning"

    def test_5xx_logs_error(self, mock_logger):
        create_error(ErrorType.INTERNAL_SERVER_ERROR, error_details="oops")
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_called_once()
        assert mock_logger.error.call_args[1]["extra"]["log_type"] == "error"

    def test_context_kwargs_included_in_message(self, mock_logger):
        exc = create_error(ErrorType.MODEL_NOT_FOUND, model_id="gpt-4")
        assert "gpt-4" in exc.detail["error"]["message"]

    def test_original_exception_logged_with_exc_info(self, mock_logger):
        orig = ValueError("original")
        create_error(ErrorType.INTERNAL_SERVER_ERROR, original_exception=orig, error_details="fail")
        call_kwargs = mock_logger.error.call_args
        assert call_kwargs[1]["exc_info"] is True
        assert call_kwargs[1]["extra"]["original_exception"] == "original"


class TestCreateErrorAllTypes:
    def test_model_not_specified_returns_400(self, mock_logger):
        exc = create_error(ErrorType.MODEL_NOT_SPECIFIED)
        assert exc.status_code == 400
        assert "Model not specified" in exc.detail["error"]["message"]

    def test_model_not_allowed_returns_403(self, mock_logger):
        exc = create_error(ErrorType.MODEL_NOT_ALLOWED, model_id="gpt-4")
        assert exc.status_code == 403
        assert "gpt-4" in exc.detail["error"]["message"]

    def test_model_not_found_returns_404(self, mock_logger):
        exc = create_error(ErrorType.MODEL_NOT_FOUND, model_id="gpt-4")
        assert exc.status_code == 404
        assert "gpt-4" in exc.detail["error"]["message"]

    def test_provider_not_found_returns_404(self, mock_logger):
        exc = create_error(ErrorType.PROVIDER_NOT_FOUND, provider_name="openai", model_id="gpt-4")
        assert exc.status_code == 404
        assert "openai" in exc.detail["error"]["message"]
        assert "gpt-4" in exc.detail["error"]["message"]

    def test_provider_config_error_returns_500(self, mock_logger):
        exc = create_error(ErrorType.PROVIDER_CONFIG_ERROR, error_details="bad config")
        assert exc.status_code == 500
        assert "bad config" in exc.detail["error"]["message"]

    def test_provider_config_error_with_original_exception(self, mock_logger):
        orig = ValueError("original")
        create_error(ErrorType.PROVIDER_CONFIG_ERROR, original_exception=orig, error_details="bad config")
        call_kwargs = mock_logger.error.call_args
        assert call_kwargs[1]["extra"]["original_exception"] == "original"

    def test_provider_network_error_returns_500(self, mock_logger):
        exc = create_error(ErrorType.PROVIDER_NETWORK_ERROR, error_details="connection refused")
        assert exc.status_code == 500
        assert "connection refused" in exc.detail["error"]["message"]

    def test_missing_api_key_returns_401(self, mock_logger):
        exc = create_error(ErrorType.MISSING_API_KEY)
        assert exc.status_code == 401

    def test_invalid_api_key_returns_401(self, mock_logger):
        exc = create_error(ErrorType.INVALID_API_KEY)
        assert exc.status_code == 401

    def test_endpoint_not_allowed_returns_403(self, mock_logger):
        exc = create_error(ErrorType.ENDPOINT_NOT_ALLOWED, endpoint_path="/v1/secret")
        assert exc.status_code == 403
        assert "/v1/secret" in exc.detail["error"]["message"]

    def test_service_unavailable_returns_503(self, mock_logger):
        exc = create_error(ErrorType.SERVICE_UNAVAILABLE, error_details="redis down")
        assert exc.status_code == 503
        assert "redis down" in exc.detail["error"]["message"]

    def test_internal_server_error_returns_500(self, mock_logger):
        exc = create_error(ErrorType.INTERNAL_SERVER_ERROR, error_details="oops")
        assert exc.status_code == 500
        assert "oops" in exc.detail["error"]["message"]
