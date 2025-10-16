import httpx
import logging
from typing import Dict, Any, Tuple, Optional
from fastapi import HTTPException, status, UploadFile

from ..core.config_manager import ConfigManager
from ..services.model_service import ModelService
from ..providers.openai import OpenAICompatibleProvider
from ..core.error_handling import ErrorHandler, ErrorContext

logger = logging.getLogger("nnp-llm-router")

class TranscriptionService:
    def __init__(self, config_manager: ConfigManager, client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.client = client
        self.model_service = model_service

    async def _validate_model_and_provider(self, model_id: str, auth_data: Tuple[str, str, Any, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], str, str]:
        user_id, _, _, _ = auth_data
        
        # Create error context
        context = ErrorContext(
            user_id=user_id,
            model_id=model_id
        )
        
        model_config = await self.model_service.retrieve_model(model_id, auth_data)
        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name")

        if not provider_name or not provider_model_name:
            raise ErrorHandler.handle_provider_config_error(
                f"Model '{model_id}' is not correctly configured with a provider or provider model name.",
                context
            )

        provider_config = self.config_manager.get_config().get("providers", {}).get(provider_name)
        if not provider_config:
            context.provider_name = provider_name
            raise ErrorHandler.handle_provider_not_found(provider_name, model_id, context)
            
        return model_config, provider_config, provider_name, provider_model_name

    async def _get_provider_instance(self, provider_config: Dict[str, Any]) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(provider_config, self.client)

    async def _process_transcription_request(self, audio_data: bytes, filename: str, content_type: str, model_id: str, auth_data: Tuple[str, str, Any, Any], response_format: str = "json", temperature: float = 0.0, language: str = None, return_timestamps: bool = False) -> Any:
        user_id, api_key, _, _ = auth_data
        logger.info(f"User {user_id} requesting transcription for model {model_id}")
        
        # Create error context
        context = ErrorContext(
            user_id=user_id,
            model_id=model_id
        )

        try:
            model_config, provider_config, provider_name, provider_model_name = await self._validate_model_and_provider(model_id, auth_data)
            provider_instance = await self._get_provider_instance(provider_config)
            
            request_params = {
                "model_id": provider_model_name,
                "response_format": response_format,
                "temperature": temperature,
                "return_timestamps": return_timestamps,
                "language": language,
                "api_key": api_key,
                "base_url": provider_config.get("base_url"),
            }

            response = await provider_instance.transcriptions(
                audio_data=audio_data,
                filename=filename,
                content_type=content_type,
                model_id=provider_model_name,
                api_key=api_key,
                base_url=provider_config.get("base_url"),
                response_format=response_format,
                temperature=temperature,
                return_timestamps=return_timestamps,
                language=language
            )

            # DEBUG логирование ответа
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "DEBUG: Transcription Response JSON",
                    extra={
                        "debug_json_data": response,
                        "debug_data_flow": "from_provider",
                        "debug_component": "transcription_service",
                        "request_id": "unknown"
                    }
                )

            return response

        except HTTPException as e:
            # Re-raise HTTPExceptions from our error handler (already logged)
            raise e
        except Exception as e:
            raise ErrorHandler.handle_internal_server_error(str(e), context, e)

    async def create_transcription(self, audio_file: UploadFile, model_id: Optional[str] = None, auth_data: Tuple[str, str, Any, Any] = None, response_format: str = "json", temperature: float = 0.0, language: str = None, return_timestamps: bool = False) -> Any:
        audio_data = await audio_file.read()
        user_id, _, allowed_models, _ = auth_data
        
        # Create error context
        context = ErrorContext(
            user_id=user_id,
            model_id=model_id
        )
        
        # DEBUG логирование параметров запроса
        if logger.isEnabledFor(logging.DEBUG):
            debug_data = {
                "model_id": model_id,
                "response_format": response_format,
                "temperature": temperature,
                "language": language,
                "return_timestamps": return_timestamps,
                "filename": audio_file.filename,
                "content_type": audio_file.content_type,
                "file_size": len(audio_data) if audio_data else 0
            }
            logger.debug(
                "DEBUG: Transcription Request Parameters",
                extra={
                    "debug_json_data": debug_data,
                    "debug_data_flow": "incoming",
                    "debug_component": "transcription_service",
                    "request_id": "unknown"  # request_id may not be available here
                }
            )
        
        # Если модель не указана, проксируем запрос как есть
        if not model_id:
            logger.info(f"User {user_id} requesting transcription without model specification")
            return await self._proxy_transcription_request(
                audio_data=audio_data,
                filename=audio_file.filename,
                content_type=audio_file.content_type,
                auth_data=auth_data,
                response_format=response_format,
                temperature=temperature,
                language=language,
                return_timestamps=return_timestamps
            )
        
        # Если модель указана, проверяем права доступа
        if allowed_models and model_id not in allowed_models:
            raise ErrorHandler.handle_model_not_allowed(model_id, context)
        
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
    
    async def _proxy_transcription_request(self, audio_data: bytes, filename: str, content_type: str, auth_data: Tuple[str, str, Any, Any], response_format: str = "json", temperature: float = 0.0, language: str = None, return_timestamps: bool = False) -> Any:
        """Проксирует запрос на бэкенд без указания модели."""
        user_id, api_key, _, _ = auth_data
        logger.info(f"User {user_id} proxying transcription request without model specification")
        
        # Create error context
        context = ErrorContext(
            user_id=user_id,
            provider_name="transcriber"
        )
        
        try:
            # Получаем конфигурацию провайдера транскрипции
            current_config = self.config_manager.get_config()
            provider_config = current_config.get("providers", {}).get("transcriber")
            
            if not provider_config:
                raise ErrorHandler.handle_provider_not_found("transcriber", "transcription", context)
            
            # Создаем экземпляр провайдера
            provider_instance = await self._get_provider_instance(provider_config)
            
            # Формируем параметры запроса с моделью по умолчанию
            # Используем первую доступную модель из конфигурации
            models = current_config.get("models", {})
            transcription_models = {k: v for k, v in models.items() if "transcriber" in v.get("provider", "")}
            
            # Если есть модели для транскрипции, используем первую
            default_model_id = list(transcription_models.keys())[0] if transcription_models else ""
            
            # Получаем конфигурацию модели по умолчанию
            model_config = transcription_models.get(default_model_id, {})
            provider_model_name = model_config.get("provider_model_name", default_model_id)
            
            request_params = {
                "response_format": response_format,
                "temperature": temperature,
                "return_timestamps": return_timestamps,
                "language": language,
                "api_key": api_key,
                "base_url": provider_config.get("base_url"),
            }

            # Отправляем запрос на провайдер с моделью по умолчанию
            response = await provider_instance.transcriptions(
                audio_data=audio_data,
                filename=filename,
                content_type=content_type,
                model_id=provider_model_name,  # Используем первую доступную модель
                api_key=api_key,
                base_url=provider_config.get("base_url"),
                response_format=response_format,
                temperature=temperature,
                return_timestamps=return_timestamps,
                language=language
            )

            # DEBUG логирование ответа
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "DEBUG: Transcription Proxy Response JSON",
                    extra={
                        "debug_json_data": response,
                        "debug_data_flow": "from_provider",
                        "debug_component": "transcription_service",
                        "request_id": "unknown"
                    }
                )

            return response

        except HTTPException as e:
            # Re-raise HTTPExceptions from our error handler (already logged)
            raise e
        except Exception as e:
            raise ErrorHandler.handle_internal_server_error(str(e), context, e)

