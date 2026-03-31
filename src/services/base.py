"""Base service with shared validation, provider instantiation, and logging."""

import httpx
from typing import Dict, Any, Tuple, Optional
from fastapi import Request

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from ..core.logging import logger
from ..core.error_handling import ErrorType, create_error


class BaseService:
    """Common base for ChatService, EmbeddingService, and TranscriptionService."""

    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        self.config_manager = config_manager
        self.httpx_client = httpx_client

    def _get_request_context(self, request: Optional[Request], auth_data: Tuple[str, str, list, list]) -> Dict[str, str]:
        """Extract request_id and user_id from request state and auth_data."""
        project_name, api_key, allowed_models, _ = auth_data

        if request and hasattr(request.state, 'request_id'):
            request_id = request.state.request_id
        else:
            request_id = "unknown"

        user_id = project_name

        return {
            "request_id": request_id,
            "user_id": user_id
        }

    def _validate_and_get_config(
        self,
        requested_model: str,
        auth_data: Tuple[str, str, list, list],
        **error_context
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
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

    def _get_provider(
        self,
        provider_config: Dict[str, Any],
        **error_context
    ) -> Any:
        """Instantiate a provider from config, raising on invalid type."""
        try:
            provider_instance = get_provider_instance(
                provider_config.get("type"),
                provider_config,
                self.httpx_client,
                self.config_manager
            )
            return provider_instance
        except ValueError as e:
            raise create_error(ErrorType.PROVIDER_CONFIG_ERROR, original_exception=e, error_details=str(e), **error_context)
    
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
