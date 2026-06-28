"""Audio transcription service with default model fallback."""
from typing import Any, Tuple, Optional
from fastapi import Request, UploadFile

from ..services.model_service import ModelService
from ..core.logging import logger
from .base import BaseService


class TranscriptionService(BaseService):
    """
    Transcription service that handles audio transcription requests.

    Supports both explicit model selection and default model fallback.
    Uses BaseService for validation, provider instantiation, and logging.
    """

    def __init__(self, config_manager, model_service: ModelService):
        super().__init__(config_manager)
        self.model_service = model_service

    async def create_transcription(
        self,
        request: Request,
        audio_file: UploadFile,
        auth_data: Tuple[str, str, Any, Any],
        model_id: Optional[str] = None,
        response_format: str = "json",
        temperature: float = 0.0,
        language: Optional[str] = None,
        return_timestamps: bool = False,
    ) -> Any:
        """Create a transcription from an audio file using the specified or default model."""
        context_dict = self._get_request_context(request)
        request_id = context_dict["request_id"]
        user_id = context_dict["user_id"]

        audio_data = await audio_file.read()

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
            request_id=request_id,
            component="transcription_service",
            data_flow="incoming"
        )

        # Use default model if not specified
        if not model_id:
            model_id = self.config_manager.default_stt_model
            logger.info(f"Using default transcription model: {model_id}",
                user_id=user_id,
                default_model=model_id
            )

        error_ctx = dict(request_id=request_id, user_id=user_id, model_id=model_id)

        async with self._guard_service_errors(error_ctx):
            model_config, provider_name, provider_model_name, provider_config = \
                self._validate_and_get_config(model_id, auth_data, **error_ctx)

            provider_instance = await self._get_provider(provider_name, provider_config, **error_ctx)

            provider_request_body = {
                "audio": {
                    "filename": audio_file.filename,
                    "content_type": audio_file.content_type,
                    "data": audio_data,
                },
                "params": {
                    "language": language,
                    "temperature": temperature,
                    "response_format": response_format,
                    "return_timestamps": return_timestamps,
                },
            }

            response = await provider_instance.transcriptions(
                provider_request_body,
                provider_model_name,
                model_config,
                request_id=request_id,
            )

            self._log_service_data(
                title="Transcription Response JSON",
                data=response,
                request_id=request_id,
                component="transcription_service",
                data_flow="from_provider"
            )

            return response
