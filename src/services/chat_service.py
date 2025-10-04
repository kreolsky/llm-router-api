
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


class StatisticsCollector:
    """
    Сборщик статистики для ответов модели
    """
    
    def __init__(self):
        self.start_time = None
        self.prompt_end_time = None
        self.completion_end_time = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
    
    def start_timing(self):
        """Начинает отсчет времени"""
        self.start_time = time.time()
    
    def mark_prompt_complete(self, prompt_tokens: int = 0):
        """Отмечает завершение обработки промпта"""
        self.prompt_end_time = time.time()
        self.prompt_tokens = prompt_tokens
    
    def mark_completion_complete(self, completion_tokens: int = 0):
        """Отмечает завершение генерации ответа"""
        self.completion_end_time = time.time()
        self.completion_tokens = completion_tokens
        self.total_tokens = self.prompt_tokens + self.completion_tokens
    
    def get_statistics(self) -> Dict[str, Any]:
        """Возвращает полную статистику"""
        if not self.start_time:
            return {}
        
        total_time = time.time() - self.start_time
        
        # Рассчитываем время обработки промпта
        prompt_time = self.prompt_end_time - self.start_time if self.prompt_end_time else 0
        
        # Рассчитываем время генерации ответа
        completion_time = self.completion_end_time - self.prompt_end_time if self.completion_end_time and self.prompt_end_time else 0
        
        # Рассчитываем токены в секунду
        prompt_tokens_per_sec = self.prompt_tokens / prompt_time if prompt_time > 0 else 0
        completion_tokens_per_sec = self.completion_tokens / completion_time if completion_time > 0 else 0
        
        return {
            "prompt_tokens": self.prompt_tokens,
            "prompt_time": round(prompt_time, 2),
            "prompt_tokens_per_sec": round(prompt_tokens_per_sec, 2),
            "completion_tokens": self.completion_tokens,
            "completion_time": round(completion_time, 2),
            "completion_tokens_per_sec": round(completion_tokens_per_sec, 2),
            "total_tokens": self.total_tokens,
            "total_time": round(total_time, 2)
        }


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
        self.statistics = StatisticsCollector()
        self.content_length = 0
    
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
        
        # Начинаем отсчет времени
        self.statistics.start_timing()
        
        full_content = ""
        stream_has_error = False
        first_token_received = False
        
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
                                # Отмечаем получение первого токена
                                if not first_token_received:
                                    first_token_received = True
                                    # Оцениваем токены промпта (приблизительно)
                                    # ВАЖНО: full_content здесь еще пустой, поэтому используем 0
                                    self.statistics.mark_prompt_complete(0)
                                
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
                        # Обновляем контент для оставшихся событий
                        full_content = self._extract_content(event_data, full_content)
            
            # Отмечаем завершение генерации и рассчитываем токены
            estimated_completion_tokens = self._estimate_tokens(full_content)
            self.statistics.mark_completion_complete(estimated_completion_tokens)
            
            # Отправляем финальное событие со статистикой
            statistics = self.statistics.get_statistics()
            if statistics:
                yield self._format_statistics_event(statistics, request_id, model_id)
            
            logger.info("Stream completed", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "content_length": len(full_content),
                "statistics": statistics
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
        
        try:
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
        except Exception as e:
            logger.error(f"Error parsing SSE event: {e}", exc_info=True)
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
        
        # Завершающее событие [DONE]
        if event_data.get('done'):
            return None
        
        # Проверяем на завершающее событие с finish_reason
        if 'choices' in event_data:
            choices = event_data.get('choices', [])
            if choices:
                choice = choices[0]
                finish_reason = choice.get('finish_reason')
                delta = choice.get('delta', {})
                
                # Если есть finish_reason и delta пустой - это завершающее событие
                if finish_reason and not delta.get('content'):
                    return None
            else:
                # Пустой список choices - пропускаем
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
            choices = event_data.get('choices', [])
            if not choices:
                return ""
            
            choice = choices[0]
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
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Приблизительная оценка количества токенов в тексте
        Использует эмпирическое правило: ~4 символа на токен для английского текста
        """
        if not text:
            return 0
        # Более точная оценка: учитываем пробелы и знаки препинания
        words = len(text.split())
        chars = len(text)
        # Комбинированная оценка: учитываем и слова, и символы
        estimated_tokens = max(words, chars // 4)
        return estimated_tokens
    
    def _format_statistics_event(self, statistics: Dict[str, Any], request_id: str, model_id: str) -> bytes:
        """Форматирует событие со статистикой в SSE формате"""
        # Форматируем статистику в ожидаемом формате
        statistics_event = {
            "prompt_tokens": statistics.get("prompt_tokens", 0),
            "prompt_time": statistics.get("prompt_time", 0),
            "prompt_tokens_per_sec": statistics.get("prompt_tokens_per_sec", 0),
            "completion_tokens": statistics.get("completion_tokens", 0),
            "completion_time": statistics.get("completion_time", 0),
            "completion_tokens_per_sec": statistics.get("completion_tokens_per_sec", 0),
            "total_tokens": statistics.get("total_tokens", 0),
            "total_time": statistics.get("total_time", 0)
        }
        
        return f"data: {json.dumps(statistics_event)}\n\n".encode('utf-8')
    


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
            # Начинаем отсчет времени для всего запроса
            statistics = StatisticsCollector()
            statistics.start_timing()
            
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            if isinstance(response_data, StreamingResponse):
                # Отмечаем завершение обработки промпта для стриминга
                # Оцениваем токены промпта на основе входных сообщений
                estimated_prompt_tokens = self._estimate_prompt_tokens(request_body)
                statistics.mark_prompt_complete(estimated_prompt_tokens)
                
                # Используем новый упрощенный процессор
                return StreamingResponse(
                    self.stream_processor.process_stream(
                        response_data.body_iterator, requested_model, request_id, user_id
                    ),
                    media_type=response_data.media_type
                )
            else:
                # Отмечаем завершение обработки промпта для нестримингового ответа
                usage = response_data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                statistics.mark_prompt_complete(prompt_tokens)
                statistics.mark_completion_complete(completion_tokens)
                
                # Получаем полную статистику
                full_statistics = statistics.get_statistics()
                
                # Обновляем ответ с расширенной статистикой
                enhanced_response = response_data.copy()
                if "usage" not in enhanced_response:
                    enhanced_response["usage"] = {}
                
                # Добавляем timing метрики к существующему usage
                enhanced_response["usage"].update(full_statistics)
                
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
                        "statistics": full_statistics,
                        "response_body_summary": {
                            "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                            "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        }
                    }
                )
                return JSONResponse(content=enhanced_response)
            
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
            logger.error(
                f"Unexpected error in chat_completions: {e}",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error"
                },
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"Internal server error: {e}", "code": "internal_server_error"}},
            )
    
    def _estimate_prompt_tokens(self, request_body: Dict[str, Any]) -> int:
        """
        Приблизительная оценка количества токенов в промпте
        На основе содержимого сообщений
        """
        messages = request_body.get("messages", [])
        if not messages:
            return 0
        
        total_text = ""
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                total_text += content + " "
            elif isinstance(content, list):
                # Обработка мультимодального контента
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        total_text += item.get("text", "") + " "
        
        # Используем ту же логику оценки, что и в StreamProcessor
        words = len(total_text.split())
        chars = len(total_text)
        estimated_tokens = max(words, chars // 4)
        return estimated_tokens