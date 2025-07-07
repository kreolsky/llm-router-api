import httpx
import logging
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status, UploadFile
import base64 # Added base64
import io # Added io

from ..core.config_manager import ConfigManager
from ..services.model_service import ModelService
from ..providers.openai import OpenAICompatibleProvider

logger = logging.getLogger("nnp-llm-router")

class TranscriptionService:
    def __init__(self, config_manager: ConfigManager, client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.client = client
        self.model_service = model_service

    async def _process_transcription_request(self, audio_data: bytes, filename: str, content_type: str, model_id: str, auth_data: Tuple[str, str, Any], response_format: str = "json", temperature: float = 0.0, language: str = None, return_timestamps: bool = False) -> Any:
        user_id, api_key, _ = auth_data
        logger.info(f"User {user_id} requesting transcription for model {model_id}")

        try:
            model_config = await self.model_service.retrieve_model(model_id)
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
            
            # Instantiate WhisperTranscriptionProvider directly
            provider_instance = OpenAICompatibleProvider(provider_config, self.client)
            
            request_params = {
                "model": provider_model_name,
                "response_format": response_format,
                "temperature": temperature,
                "return_timestamps": return_timestamps, # Pass return_timestamps
            }
            if language:
                request_params["language"] = language

            response = await provider_instance.transcriptions(
                audio_data=audio_data, # Pass raw audio data
                filename=filename,
                content_type=content_type,
                model_id=provider_model_name,
                api_key=api_key,
                base_url=provider_config.get("base_url"),
                **request_params
            )

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

    async def create_transcription(self, audio_file: UploadFile, model_id: str, auth_data: Tuple[str, str, Any], response_format: str = "json", temperature: float = 0.0, language: str = None, return_timestamps: bool = False) -> Any:
        audio_data = await audio_file.read()
        return await self._process_transcription_request(
            audio_data=audio_data,
            filename=audio_file.filename,
            content_type=audio_file.content_type,
            model_id=model_id,
            auth_data=auth_data,
            response_format=response_format,
            temperature=temperature,
            language=language,
            return_timestamps=return_timestamps # Pass return_timestamps
        )

