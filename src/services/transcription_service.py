"""Audio transcription service with default model fallback."""
from typing import Any

from fastapi import Request, UploadFile

from ..core.context import AuthContext
from ..core.logging import logger
from ..services.model_service import ModelService
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
        auth_context: AuthContext,
        model_id: str | None = None,
        response_format: str = "json",
        temperature: float = 0.0,
        language: str | None = None,
        return_timestamps: bool = False,
    ) -> Any:
        """Create a transcription from an audio file using the specified or default model."""
        ctx = self._get_request_context(request)
        request_id = ctx.request_id
        user_id = ctx.user_id

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
            model_id = self.config_manager.settings.default_stt_model
            logger.info(f"Using default transcription model: {model_id}",
                user_id=user_id,
                default_model=model_id
            )

        # Transcriptions carry no usage block: tokens stay 0 and has_usage
        # stays False — the row still makes transcriptions visible in stats.
        async with self._guard_service_errors(
            {"request_id": request_id, "user_id": user_id, "model_id": model_id}
        ):
            # ARCH: multipart cannot enter the JSON wrapper, so transcription
            # rides the body-agnostic resolver — the same funnel
            # _prepare_dispatch delegates to after parsing its JSON body.
            target = await self._resolve_target(request, auth_context, model_id)

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

            response = await target.provider.transcriptions(
                provider_request_body,
                target.provider_model_name,
                target.model_config,
                request_id=request_id,
                extra_headers=target.identity_headers,
            )

            self._log_service_data(
                title="Transcription Response JSON",
                data=response,
                request_id=request_id,
                component="transcription_service",
                data_flow="from_provider"
            )

            return response
