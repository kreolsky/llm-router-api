import httpx
import os
from typing import Dict, Any, Tuple, Optional
from fastapi import HTTPException, UploadFile

from ..core.config_manager import ConfigManager
from ..services.model_service import ModelService
from ..providers.openai import OpenAICompatibleProvider
from ..core.error_handling import ErrorHandler, ErrorContext
from ..core.logging import logger  # Using the simplified universal Logger


class TranscriptionService:
    """
    Ultra-minimal transcription service that handles audio transcription requests.
    
    This service provides a simplified implementation that:
    - Uses model_id directly without unnecessary variables
    - Handles both explicit model requests and default model fallback
    - Maintains proper access control using the project's standard pattern
    - Eliminates hardcoded provider references
    - Provides comprehensive error handling and logging
    """
    
    def __init__(self, config_manager: ConfigManager, client: httpx.AsyncClient, model_service: ModelService):
        """
        Initialize the transcription service.
        
        Args:
            config_manager: Configuration manager instance
            client: HTTP client for making requests
            model_service: Model service for retrieving model configurations
        """
        self.config_manager = config_manager
        self.client = client
        self.model_service = model_service

    async def _get_provider_instance(self, provider_config: Dict[str, Any]) -> OpenAICompatibleProvider:
        """
        Create a provider instance for the given configuration.
        
        Args:
            provider_config: Provider configuration dictionary
            
        Returns:
            OpenAICompatibleProvider instance
        """
        return OpenAICompatibleProvider(provider_config, self.client)

    async def create_transcription(
        self,
        audio_file: UploadFile,
        model_id: Optional[str] = None,
        auth_data: Tuple[str, str, Any, Any] = None,
        response_format: str = "json",
        temperature: float = 0.0,
        language: str = None,
        return_timestamps: bool = False
    ) -> Any:
        """
        Create a transcription from an audio file using the specified or default model.
        
        This method implements the ultra-minimal approach:
        - If model_id is provided: validates access and uses the specified model
        - If no model_id is provided: uses DEFAULT_STT_MODEL from environment
        - Maintains proper access control using the project's standard pattern
        - Eliminates unnecessary helper methods and variables
        
        Args:
            audio_file: Audio file to transcribe
            model_id: Optional model ID to use for transcription
            auth_data: Authentication data tuple (user_id, api_key, allowed_models, allowed_endpoints)
            response_format: Format of the transcription response
            temperature: Temperature parameter for transcription
            language: Language code for transcription
            return_timestamps: Whether to include timestamps in the response
            
        Returns:
            Transcription response from the provider
            
        Raises:
            HTTPException: For access denied, configuration errors, or internal errors
        """
        audio_data = await audio_file.read()
        user_id, api_key, allowed_models, _ = auth_data
        
        # DEBUG logging of request parameters
        logger.debug_data(
            title="Transcription Request Parameters",
            data={
                "model_id": model_id,
                "response_format": response_format,
                "temperature": temperature,
                "language": language,
                "return_timestamps": return_timestamps,
                "filename": audio_file.filename,
                "content_type": audio_file.content_type,
                "file_size": len(audio_data) if audio_data else 0
            },
            request_id="unknown",  # request_id may not be available here
            component="transcription_service",
            data_flow="incoming"
        )
        
        # Determine which model to use
        if model_id:
            # Model specified by user - check access using the same logic as model_service.py
            if allowed_models and model_id not in allowed_models:
                logger.warning(f"User {user_id} denied access to model {model_id}", extra={
                    "user_id": user_id,
                    "model_id": model_id,
                    "operation": "access_denied"
                })
                context = ErrorContext(user_id=user_id, model_id=model_id)
                raise ErrorHandler.handle_model_not_allowed(model_id, context)
        else:
            # No model specified - use default from .env or fallback to stt/dummy
            model_id = os.getenv("DEFAULT_STT_MODEL", "stt/dummy")
            
            # Log that we're using default model
            logger.info(f"User {user_id} requesting transcription without model, using default", extra={
                "user_id": user_id,
                "default_model": model_id,
                "operation": "transcription_without_model"
            })
        
        # Create error context
        context = ErrorContext(user_id=user_id, model_id=model_id)
        
        try:
            # Get model configuration
            model_config = await self.model_service.retrieve_model(model_id, auth_data)
            provider_name = model_config.get("provider")
            provider_model_name = model_config.get("provider_model_name")
            
            if not provider_name or not provider_model_name:
                raise ErrorHandler.handle_provider_config_error(
                    f"Model '{model_id}' is not correctly configured",
                    context
                )
            
            # Get provider configuration
            provider_config = self.config_manager.get_config().get("providers", {}).get(provider_name)
            if not provider_config:
                context.provider_name = provider_name
                raise ErrorHandler.handle_provider_not_found(provider_name, model_id, context)
            
            # Create provider instance
            provider_instance = await self._get_provider_instance(provider_config)
            
            # Send request to provider
            response = await provider_instance.transcriptions(
                audio_data=audio_data,
                filename=audio_file.filename,
                content_type=audio_file.content_type,
                model_id=provider_model_name,
                api_key=api_key,
                base_url=provider_config.get("base_url"),
                response_format=response_format,
                temperature=temperature,
                return_timestamps=return_timestamps,
                language=language
            )
            
            # DEBUG logging of response
            logger.debug_data(
                title="Transcription Response JSON",
                data=response,
                request_id="unknown",
                component="transcription_service",
                data_flow="from_provider"
            )
            
            return response
            
        except HTTPException as e:
            # Re-raise HTTPExceptions from our error handler (already logged)
            raise e
        except Exception as e:
            raise ErrorHandler.handle_internal_server_error(str(e), context, e)

