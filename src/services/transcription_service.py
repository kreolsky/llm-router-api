import httpx
import os
from typing import Dict, Any, Tuple, Optional
from fastapi import HTTPException, UploadFile

from ..core.config_manager import ConfigManager
from ..services.model_service import ModelService
from ..core.error_handling import ErrorHandler, ErrorContext
from ..core.logging import logger
from .base import BaseService


class TranscriptionService(BaseService):
    """
    Transcription service that handles audio transcription requests.

    Supports both explicit model selection and default model fallback.
    Uses BaseService for validation, provider instantiation, and logging.
    """

    def __init__(self, config_manager: ConfigManager, client: httpx.AsyncClient, model_service: ModelService):
        super().__init__(config_manager, client)
        self.model_service = model_service

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
        """
        audio_data = await audio_file.read()
        user_id, api_key, allowed_models, _ = auth_data

        self._log_service_data(
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
            request_id="unknown",
            component="transcription_service",
            data_flow="incoming"
        )

        # Use default model if not specified
        if not model_id:
            model_id = os.getenv("DEFAULT_STT_MODEL", "stt/dummy")
            logger.info(f"Using default transcription model: {model_id}", extra={
                "user_id": user_id,
                "default_model": model_id
            })

        context = ErrorContext(user_id=user_id, model_id=model_id)

        try:
            # Validate model access and get configuration (reuse BaseService)
            model_config, provider_name, provider_model_name, provider_config = \
                self._validate_and_get_config(model_id, auth_data, context)

            provider_instance = self._get_provider(provider_config, context)

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

            self._log_service_data(
                title="Transcription Response JSON",
                data=response,
                request_id="unknown",
                component="transcription_service",
                data_flow="from_provider"
            )

            return response

        except HTTPException as e:
            raise e
        except Exception as e:
            raise ErrorHandler.handle_internal_server_error(str(e), context, e)
