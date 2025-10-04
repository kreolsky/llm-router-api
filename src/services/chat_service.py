
"""
Упрощенный ChatService со встроенным StreamProcessor
"""
import httpx
import json
import time
import codecs
from typing import Dict, Any, Tuple, AsyncGenerator, Optional, List

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from .model_service import ModelService
from ..core.exceptions import ProviderStreamError, ProviderNetworkError
from ..logging.config import logger


class StreamProcessor:
    """
    Единый процессор для всего стриминга - заменяет 4 старых класса
    Приоритет: простота поддержки и производительность
    """
    
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        """
        Args:
            max_buffer_size: Максимальный размер буфера в байтах
        """
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.buffer = ""
    
    async def process_stream(self, 
                           provider_stream: AsyncGenerator[bytes, None],
                           model_id: str,
                           request_id: str,
                           user_id: str) -> AsyncGenerator[bytes, None]:
        """
        Основной метод обработки стриминга
        
        Args:
            provider_stream: Стрим от провайдера
            model_id: ID модели
            request_id: ID запроса
            user_id: ID пользователя
            
        Yields:
            SSE отформатированные чанки
        """
        logger.info("Starting stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id
        })
        
        full_content = ""
        stream_has_error = False
        
        try:
            event_count = 0
            async for chunk in provider_stream:
                try:
                    # Декодируем и обрабатываем чанк
                    decoded_chunk = self.utf8_decoder.decode(chunk, final=False)
                    if decoded_chunk:
                        self.buffer += decoded_chunk
                        
                        # Обрабатываем события из буфера
                        events = self._extract_events()
                        for event_data in events:
                            event_count += 1
                            chunk_bytes = await self._process_event_data(
                                event_data, model_id, request_id, full_content
                            )
                            if chunk_bytes:
                                yield chunk_bytes
                                # Обновляем контент для следующего события
                                full_content = self._extract_content(event_data, full_content)
                
                except Exception as e:
                    logger.error("Stream processing error", extra={
                        "request_id": request_id,
                        "user_id": user_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }, exc_info=True)
                    
                    yield self._format_error(e)
                    stream_has_error = True
                    break
                    
        except Exception as e:
            logger.error("Critical stream error", extra={
                "request_id": request_id,
                "user_id": user_id,
                "error": str(e)
            }, exc_info=True)
            
            yield self._format_error(e)
            stream_has_error = True
        
        # Завершаем стрим если не было ошибок
        if not stream_has_error:
            # Обрабатываем оставшиеся данные в буфере
            if self.buffer.strip():
                events = self._extract_events(final=True)
                for event_data in events:
                    chunk_bytes = await self._process_event_data(
                        event_data, model_id, request_id, full_content
                    )
                    if chunk_bytes:
                        yield chunk_bytes
            
            logger.info("Stream completed", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "content_length": len(full_content)
            })
            
            yield b"data: [DONE]\n\n"
        
        # Очищаем буфер
        self._clear_buffer()
    
    def _extract_events(self, final: bool = False) -> List[Dict[str, Any]]:
        """
        Извлекает события из буфера
        
        Args:
            final: Флаг окончания стрима
            
        Returns:
            Список распарсенных событий
        """
        events = []
        
        if not self.buffer:
            return events
        
        # Определяем формат по первым данным
        stream_format = self._detect_format(self.buffer)
        
        if stream_format == 'sse':
            events = self._extract_sse_events(final)
        else:
            events = self._extract_ndjson_events(final)
        
        return events
    
    def _detect_format(self, event: str) -> str:
        """
        Определяет формат стрима
        
        Args:
            event: Строка события
            
        Returns:
            'sse' или 'ndjson'
        """
        event_stripped = event.strip()
        
        # SSE события содержат 'data:' или начинаются с ':'
        if 'data:' in event_stripped or event_stripped.startswith(':'):
            return 'sse'
        
        # Пробуем распарсить как JSON для NDJSON
        try:
            json.loads(event_stripped)
            return 'ndjson'
        except json.JSONDecodeError:
            # По умолчанию SSE (более распространенный формат)
            return 'sse'
    
    def _extract_sse_events(self, final: bool) -> List[Dict[str, Any]]:
        """Извлекает SSE события"""
        events = []
        
        # Поддерживаем оба формата разделителей: \n\n и \r\n\r\n
        # Сначала пробуем найти любой из разделителей
        separator_positions = []
        
        # Ищем позиции всех возможных разделителей
        for separator in ['\r\n\r\n', '\n\n']:
            pos = self.buffer.find(separator)
            if pos != -1:
                separator_positions.append((pos, separator))
        
        # Сортируем по позиции (самый ранний разделитель)
        separator_positions.sort(key=lambda x: x[0])
        
        # Обрабатываем события пока есть разделители
        while separator_positions:
            pos, separator = separator_positions[0]
            event_raw = self.buffer[:pos]
            self.buffer = self.buffer[pos + len(separator):]
            
            event_data = self._parse_sse_event(event_raw)
            if event_data:
                events.append(event_data)
            
            # Обновляем позиции для оставшегося буфера
            separator_positions = []
            for sep in ['\r\n\r\n', '\n\n']:
                pos = self.buffer.find(sep)
                if pos != -1:
                    separator_positions.append((pos, sep))
            separator_positions.sort(key=lambda x: x[0])
        
        # Если final=True, обрабатываем оставшиеся данные
        if final and self.buffer.strip():
            event_data = self._parse_sse_event(self.buffer)
            if event_data:
                events.append(event_data)
            self.buffer = ""
        
        return events
    
    def _parse_sse_event(self, event_raw: str) -> Optional[Dict[str, Any]]:
        """Парсит SSE событие"""
        if not event_raw.strip():
            return None
        
        for line in event_raw.split('\n'):
            line = line.strip()
            
            # Пропускаем комментарии
            if line.startswith(':'):
                continue
            
            if line.startswith('data: '):
                data_part = line[6:].strip()
                
                # [DONE] - валидное завершающее событие
                if data_part == '[DONE]':
                    return {'done': True}
                
                # Парсим JSON
                try:
                    return json.loads(data_part)
                except json.JSONDecodeError:
                    return None
        
        return None
    
    def _extract_ndjson_events(self, final: bool) -> List[Dict[str, Any]]:
        """Извлекает NDJSON события"""
        events = []
        
        lines = self.buffer.split('\n')
        if not final:
            self.buffer = lines[-1]  # Сохраняем неполную строку
            lines = lines[:-1]
        else:
            self.buffer = ""
        
        for line in lines:
            if line.strip():
                try:
                    event_data = json.loads(line)
                    events.append(event_data)
                except json.JSONDecodeError:
                    continue
        
        return events
    
    async def _process_event_data(self, 
                                event_data: Dict[str, Any],
                                model_id: str,
                                request_id: str,
                                full_content: str) -> Optional[bytes]:
        """
        Обрабатывает распарсенные данные события
        
        Args:
            event_data: Распарсенные данные события
            model_id: ID модели
            request_id: ID запроса
            full_content: Текущий полный контент
            
        Returns:
            SSE отформатированный чанк или None
        """
        if not event_data:
            return None
        
        # Обработка ошибок
        if 'error' in event_data:
            return self._format_error(Exception(event_data['error']))
        
        # Завершающее событие
        if event_data.get('done'):
            return None
        
        # Извлекаем контент
        content = self._extract_content_from_data(event_data)
        if not content:
            return None
        
        # Формируем SSE чанк
        return self._format_sse_chunk(content, model_id, request_id)
    
    def _extract_content(self, event_data: Dict[str, Any], current_content: str) -> str:
        """Извлекает контент и обновляет полный контент"""
        content = self._extract_content_from_data(event_data)
        return current_content + content if content else current_content
    
    def _extract_content_from_data(self, event_data: Dict[str, Any]) -> str:
        """Извлекает контент из распарсенных данных"""
        # SSE формат (OpenAI)
        if 'choices' in event_data:
            choice = event_data.get('choices', [{}])[0]
            delta = choice.get('delta', {})
            
            # OpenAI формат: delta.content
            if 'content' in delta:
                return delta.get('content', '')
            
            # Ollama формат: delta с полями role, content, tool_calls
            if 'role' in delta and 'content' in delta:
                return delta.get('content', '')
        
        # NDJSON формат (Ollama)
        if 'message' in event_data:
            return event_data.get('message', {}).get('content', '')
        
        return ""
    
    def _format_sse_chunk(self, content: str, model_id: str, request_id: str) -> bytes:
        """Форматирует контент в SSE чанк"""
        openai_chunk = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "logprobs": None,
                    "finish_reason": None
                }
            ]
        }
        
        return f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
    
    def _format_error(self, error: Exception) -> bytes:
        """Форматирует ошибку в SSE формате"""
        if isinstance(error, ProviderStreamError):
            message = error.message
            code = error.error_code
        elif isinstance(error, ProviderNetworkError):
            message = error.message
            code = "provider_network_error"
        else:
            message = f"An unexpected error occurred during streaming: {error}"
            code = "unexpected_streaming_error"
        
        error_payload = {
            "error": {
                "message": message,
                "type": "api_error",
                "code": code,
                "param": None
            }
        }
        
        return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
    
    def _clear_buffer(self):
        """Очищает буфер и сбрасывает декодер"""
        self.buffer = ""
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')


class ChatService:
    """Упрощенная координация обработки чат-запросов"""
    
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.httpx_client = httpx_client
        self.model_service = model_service
        
        # Единый процессор вместо 4 отдельных компонентов
        self.stream_processor = StreamProcessor()
    
    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list]) -> Any:
        """
        Основной метод обработки чат-запросов
        
        Args:
            request: FastAPI запрос
            auth_data: Данные аутентификации (project_name, api_key, allowed_models)
            
        Returns:
            StreamingResponse или JSONResponse
        """
        project_name, api_key, allowed_models = auth_data
        request_id = request.state.request_id
        user_id = project_name

        request_body = await request.json()
        requested_model = request_body.get("model")

        # Логирование запроса
        logger.info(
            "Chat Completion Request",
            extra={
                "log_type": "request",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "request_body_summary": {
                    "model": requested_model,
                    "messages_count": len(request_body.get("messages", [])),
                    "first_message_content": request_body.get("messages", [{}])[0].get("content") if request_body.get("messages") else None
                }
            }
        )

        # Валидация
        if not requested_model:
            error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
            logger.error(
                "Model not specified in request",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail,
            )

        if allowed_models and requested_model not in allowed_models:
            error_detail = {"error": {"message": f"Model '{requested_model}' not allowed for this API key", "code": "model_not_allowed"}}
            logger.error(
                f"Model '{requested_model}' not allowed for this API key",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_detail,
            )

        # Прямое извлечение конфигурации
        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        
        if not model_config:
            error_detail = {"error": {"message": f"Model '{requested_model}' not found in configuration", "code": "model_not_found"}}
            logger.error(
                f"Model '{requested_model}' not found in configuration",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail,
            )

        # Получение конфигурации провайдера
        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        provider_config = current_config.get("providers", {}).get(provider_name)
        
        if not provider_config:
            error_detail = {"error": {"message": f"Provider '{provider_name}' for model '{requested_model}' not found in configuration", "code": "provider_not_found"}}
            logger.error(
                f"Provider '{provider_name}' for model '{requested_model}' not found in configuration",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )

        # Получение провайдера
        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            error_detail = {"error": {"message": f"Provider configuration error: {e}", "code": "provider_config_error"}}
            logger.error(
                f"Provider configuration error: {e}",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
        
        try:
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            if isinstance(response_data, StreamingResponse):
                # Используем новый упрощенный процессор
                return StreamingResponse(
                    self.stream_processor.process_stream(
                        response_data.body_iterator, requested_model, request_id, user_id
                    ),
                    media_type=response_data.media_type
                )
            else:
                usage = response_data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

                logger.info(
                    "Chat Completion Response",
                    extra={
                        "log_type": "response",
                        "request_id": request_id,
                        "user_id": user_id,
                        "model_id": requested_model,
                        "http_status_code": status.HTTP_200_OK,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "response_body_summary": {
                            "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                            "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        }
                    }
                )
                return JSONResponse(content=response_data)
            
        except HTTPException as e:
            logger.error(
                f"HTTPException in chat_completions: {e.detail.get('error', {}).get('message', str(e))}",
                extra={
                    "status_code": e.status_code,
                    "detail": e.detail,
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error"
                }
            )
            raise e
        except Exception as e:
            logger