import httpx
import logging
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status, UploadFile

from ..core.config_manager import ConfigManager
from ..services.model_service import ModelService
from ..providers import get_provider_instance
from ..utils.cost_calculator import CostCalculator

logger = logging.getLogger("nnp-llm-router")

class TranscriptionService:
    def __init__(self, config_manager: ConfigManager, client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.client = client
        self.model_service = model_service
        # self.cost_calculator = CostCalculator(config_manager) # Removed as it's not instantiated with arguments

    async def create_transcription(self, audio_file: UploadFile, model_id: str, auth_data: Tuple[str, str, Any], response_format: str = "json", temperature: float = 0.0, language: str = None) -> Any:
        user_id, _, _ = auth_data # Unpack only the user_id, discard api_key and allowed_models
        logger.info(f"User {user_id} requesting transcription for model {model_id}")

        try:
            model_config = await self.model_service.retrieve_model(model_id)
            # retrieve_model raises HTTPException if model not found, so no need for if not model_config

            provider_name = model_config.get("provider")
            provider_model_name = model_config.get("provider_model_name")
            
            if not provider_name or not provider_model_name:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"error": {"message": f"Model '{model_id}' is not correctly configured with a provider or provider model name.", "code": "model_config_error"}},
                )

            provider_config = self.config_manager.get_config().get("providers", {}).get(provider_name)
            if not provider_config:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"error": {"message": f"Provider '{provider_name}' not found.", "code": "provider_not_found"}},
                )
            
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.client)
            
            # Prepare the request body for the provider
            # The provider will handle the file upload and other parameters
            request_params = {
                "model": provider_model_name,
                "response_format": response_format,
                "temperature": temperature,
            }
            if language:
                request_params["language"] = language

            # Call the provider's transcription method
            response = await provider_instance.transcriptions(
                audio_file=audio_file,
                request_params=request_params,
                model_config=model_config
            )

            # TODO: Implement cost calculation for transcription
            # self.cost_calculator.record_usage(user_id, model_id, prompt_tokens, completion_tokens, "chat")

            return response

        except HTTPException as e:
            logger.error(f"HTTPException in TranscriptionService: {e.detail}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error in TranscriptionService: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"An unexpected error occurred: {e}", "code": "internal_server_error"}},
            )