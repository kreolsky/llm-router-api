"""
Base Service Module

This module provides the BaseService class that contains common functionality
shared across all service implementations in the NNP LLM Router system.

The BaseService class centralizes:
- Request context extraction (request_id, user_id)
- Model validation and configuration retrieval
- Provider instantiation and error handling
- Standardized logging for requests and responses

By extracting this common functionality, we reduce code duplication and improve
maintainability across the service layer.

Refactoring Phase 2: This file was created to eliminate ~150 lines of duplicate
code across ChatService, EmbeddingService, and TranscriptionService.
"""

import httpx
from typing import Dict, Any, Tuple, Optional
from fastapi import Request

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from ..core.logging import logger
from ..core.error_handling import ErrorHandler, ErrorContext


class BaseService:
    """
    Base service class providing common functionality for all services.
    
    This class centralizes shared logic across ChatService, EmbeddingService,
    and TranscriptionService to reduce code duplication and improve maintainability.
    
    The BaseService provides:
    - Request context extraction from FastAPI Request objects
    - Model validation and configuration retrieval
    - Provider instantiation with error handling
    - Standardized logging for service operations
    
    Attributes:
        config_manager (ConfigManager): Configuration manager instance for
            accessing model and provider configurations
        httpx_client (httpx.AsyncClient): HTTP client for making external
            requests to AI providers
    """
    
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        """
        Initialize BaseService with required dependencies.
        
        Args:
            config_manager: Configuration manager instance for accessing
                model and provider configurations
            httpx_client: Async HTTP client for making external requests
                to AI providers
        """
        self.config_manager = config_manager
        self.httpx_client = httpx_client
    
    def _get_request_context(self, request: Optional[Request], auth_data: Tuple[str, str, list, list]) -> Dict[str, str]:
        """
        Extract request context (request_id and user_id) from request and auth data.
        
        This method standardizes the extraction of request metadata across all services.
        It handles both FastAPI Request objects and cases where request_id is not available.
        
        Args:
            request: FastAPI Request object (optional, may be None for some operations)
            auth_data: Authentication data tuple containing:
                - project_name (str): Name of the project making the request
                - api_key (str): API key for authentication
                - allowed_models (list): List of model IDs allowed for this API key
                - allowed_endpoints (list): List of endpoints allowed for this API key
        
        Returns:
            Dictionary containing:
                - request_id (str): Unique identifier for the request
                - user_id (str): User/project identifier (uses project_name)
        
        Example:
            >>> context = self._get_request_context(request, auth_data)
            >>> request_id = context["request_id"]
            >>> user_id = context["user_id"]
        """
        project_name, api_key, allowed_models, _ = auth_data
        
        # Extract request_id from request state if available
        if request and hasattr(request.state, 'request_id'):
            request_id = request.state.request_id
        else:
            # Fallback for cases where request_id is not available
            request_id = "unknown"
        
        # Use project_name as user_id (consistent with existing pattern)
        user_id = project_name
        
        return {
            "request_id": request_id,
            "user_id": user_id
        }
    
    def _validate_and_get_config(
        self,
        requested_model: str,
        auth_data: Tuple[str, str, list, list],
        context: ErrorContext
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        """
        Validate model access and retrieve configuration.
        
        This method centralizes the common validation logic across all services:
        1. Check if model is specified
        2. Check if model is allowed for the user
        3. Retrieve model configuration
        4. Retrieve provider configuration
        5. Return all necessary configuration data
        
        Args:
            requested_model: Model ID requested by the user
            auth_data: Authentication data tuple containing:
                - project_name (str): Name of the project making the request
                - api_key (str): API key for authentication
                - allowed_models (list): List of model IDs allowed for this API key
                - allowed_endpoints (list): List of endpoints allowed for this API key
            context: ErrorContext for error handling with request metadata
        
        Returns:
            Tuple containing:
                - model_config (Dict[str, Any]): Model configuration dictionary
                - provider_name (str): Name of the provider for this model
                - provider_model_name (str): Provider-specific model name
                - provider_config (Dict[str, Any]): Provider configuration dictionary
        
        Raises:
            HTTPException: With appropriate status codes:
                - 400: Model not specified in request
                - 403: Model not allowed for this API key
                - 404: Model or provider not found in configuration
        
        Example:
            >>> context = ErrorContext(request_id="123", user_id="user1", model_id="gpt-4")
            >>> model_config, provider_name, provider_model_name, provider_config = \\
            ...     self._validate_and_get_config("gpt-4", auth_data, context)
        """
        project_name, api_key, allowed_models, _ = auth_data
        
        # Validate that model is specified
        if not requested_model:
            raise ErrorHandler.handle_model_not_specified(context)
        
        # Validate model access permissions
        if allowed_models and requested_model not in allowed_models:
            raise ErrorHandler.handle_model_not_allowed(requested_model, context)
        
        # Retrieve current configuration
        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        
        # Validate model exists in configuration
        if not model_config:
            raise ErrorHandler.handle_model_not_found(requested_model, context)
        
        # Extract provider information
        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        
        # Retrieve provider configuration
        provider_config = current_config.get("providers", {}).get(provider_name)
        
        # Validate provider exists
        if not provider_config:
            raise ErrorHandler.handle_provider_not_found(provider_name, requested_model, context)
        
        return model_config, provider_name, provider_model_name, provider_config
    
    def _get_provider(
        self,
        provider_config: Dict[str, Any],
        context: ErrorContext
    ) -> Any:
        """
        Instantiate a provider instance based on configuration.
        
        This method centralizes provider instantiation logic and handles
        configuration errors consistently across all services.
        
        Args:
            provider_config: Provider configuration dictionary containing
                at minimum the 'type' field specifying the provider type
            context: ErrorContext for error handling with request metadata
        
        Returns:
            Provider instance (BaseProvider subclass) ready for use
        
        Raises:
            HTTPException: With status 500 if provider configuration is invalid
                or provider type is not recognized
        
        Example:
            >>> context = ErrorContext(request_id="123", user_id="user1", model_id="gpt-4")
            >>> provider = self._get_provider(provider_config, context)
            >>> response = await provider.chat_completions(...)
        """
        try:
            provider_instance = get_provider_instance(
                provider_config.get("type"),
                provider_config,
                self.httpx_client,
                self.config_manager
            )
            return provider_instance
        except ValueError as e:
            raise ErrorHandler.handle_provider_config_error(str(e), context, e)
    
    def _log_service_data(
        self,
        title: str,
        data: Any,
        request_id: str,
        component: str,
        data_flow: str = "incoming"
    ) -> None:
        """
        Log service data with standardized format.
        
        This method provides a consistent logging interface across all services
        for debugging and monitoring purposes. It uses the debug_data logger
        to capture detailed information about requests and responses.
        
        Args:
            title: Descriptive title for the logged data (e.g., "Chat Completion Request JSON")
            data: The data to log (can be dict, list, string, or any serializable type)
            request_id: Unique identifier for the request
            component: Name of the service component (e.g., "chat_service", "embedding_service")
            data_flow: Direction of data flow:
                - "incoming": Data coming into the service (requests)
                - "from_provider": Data coming from the provider (responses)
                - "outgoing": Data leaving the service (responses to client)
        
        Example:
            >>> self._log_service_data(
            ...     title="Chat Completion Request JSON",
            ...     data=request_body,
            ...     request_id="123",
            ...     component="chat_service",
            ...     data_flow="incoming"
            ... )
        """
        logger.debug_data(
            title=title,
            data=data,
            request_id=request_id,
            component=component,
            data_flow=data_flow
        )
