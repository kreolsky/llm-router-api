"""Base service with shared validation, provider instantiation, and logging."""
# SYSTEM: service-layer — validate access, resolve provider, dispatch

import contextlib
from typing import Any

from fastapi import HTTPException, Request

from ..core.config_manager import ConfigManager
from ..core.context import RequestContext, request_context
from ..core.error_handling import ErrorType, create_error
from ..core.identity_headers import compile_passthrough_spec, match_passthrough
from ..core.logging import logger
from ..core.opencode_identity import opencode_session_headers
from ..providers import get_provider_instance


class BaseService:
    """Common base for ChatService, EmbeddingService, ModelService, and TranscriptionService."""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    @contextlib.asynccontextmanager
    async def _guard_service_errors(self, error_ctx: dict[str, Any]):
        """Wrap a service block: re-raise HTTPException as-is, wrap other errors.

        De-duplicates the identical try/except error-wrapping pattern across
        chat/embedding/transcription services.
        """
        try:
            yield
        except HTTPException:
            raise
        except Exception as e:
            raise create_error(
                ErrorType.INTERNAL_SERVER_ERROR,
                original_exception=e,
                error_details=str(e),
                **error_ctx,
            )

    def _get_request_context(self, request: Request | None) -> RequestContext:
        """Return the typed RequestContext carried by the request."""
        return request_context(request)

    def _extract_passthrough_headers(self, request: Request | None,
                                     spec: Any | None = None) -> dict[str, str]:
        """Pick whitelisted headers off the client request, canonical casing.

        spec is the provider's compiled passthrough whitelist; None falls back
        to the default set (core/identity_headers.py).
        """
        if request is None:
            return {}
        if spec is None:
            spec = compile_passthrough_spec()
        forwarded: dict[str, str] = {}
        for name, value in request.headers.items():
            canonical = match_passthrough(name, spec)
            if canonical is not None:
                forwarded[canonical] = value
        return forwarded

    def _build_identity_headers(self, provider_instance: Any,
                                request: Request | None) -> dict[str, str] | None:
        """Per-request upstream headers for providers with an identity profile.

        passthrough: forward the client's whitelisted harness headers verbatim.
        opencode: synthesize session headers (registry keyed by provider name +
        project_name); real client headers still win over the synthetic set.
        Returns None when the provider has no profile (behavior unchanged).
        """
        identity = getattr(provider_instance, "identity", None)
        if not identity:
            return None
        passthrough = self._extract_passthrough_headers(
            request, getattr(provider_instance, "passthrough_spec", None))
        if identity == "passthrough":
            return passthrough or None
        if identity == "opencode":
            ctx = request_context(request)
            registry_key = f"{getattr(provider_instance, 'provider_name', 'unknown')}:{ctx.project_name}"
            synthetic = opencode_session_headers(registry_key, self.config_manager.opencode_session_ttl)
            return {**synthetic, **passthrough}
        return None

    def _validate_and_get_config(
        self,
        requested_model: str,
        auth_data: tuple[str, str, list, list],
        **error_context
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        """Validate model access and return (model_config, provider_name, provider_model_name, provider_config)."""
        project_name, api_key, allowed_models, _ = auth_data

        if not requested_model:
            raise create_error(ErrorType.MODEL_NOT_SPECIFIED, **error_context)

        # INVARIANT: check allowed_models BEFORE checking existence to prevent
        # information leakage about configured models
        if allowed_models and requested_model not in allowed_models:
            raise create_error(ErrorType.MODEL_NOT_ALLOWED, **error_context)

        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)

        if not model_config:
            raise create_error(ErrorType.MODEL_NOT_FOUND, **error_context)

        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        provider_config = current_config.get("providers", {}).get(provider_name)

        if not provider_config:
            raise create_error(ErrorType.PROVIDER_NOT_FOUND, provider_name=provider_name, **error_context)

        return model_config, provider_name, provider_model_name, provider_config

    async def _get_provider(
        self,
        provider_name: str,
        provider_config: dict[str, Any],
        **error_context
    ) -> Any:
        """Instantiate a provider from config (cache lookup under lock), raising on invalid type."""
        return await get_provider_instance(
            provider_name,
            provider_config,
            self.config_manager
        )
    
    def _log_service_data(
        self,
        title: str,
        data: Any,
        request_id: str,
        component: str,
        data_flow: str = "incoming"
    ) -> None:
        """Log request/response data via debug_data."""
        logger.debug_data(
            title=title,
            data=data,
            request_id=request_id,
            component=component,
            data_flow=data_flow
        )
