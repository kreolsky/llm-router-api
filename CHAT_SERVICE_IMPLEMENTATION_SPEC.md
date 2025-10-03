# Спецификация реализации рефакторинга ChatService

## Обзор

Этот документ содержит полную спецификацию кода для реализации рефакторинга ChatService в соответствии с планом, описанным в [`CHAT_SERVICE_REFACTORING_PLAN.md`](CHAT_SERVICE_REFACTORING_PLAN.md).

## Структура файлов для создания

```
src/services/chat/
├── __init__.py
├── validator.py          # ChatRequestValidator
├── buffer_manager.py     # StreamBufferManager
├── format_processor.py   # StreamFormatProcessor
├── error_handler.py      # StreamingErrorHandler
├── logger.py            # ChatLogger
├── streaming_handler.py # StreamingHandler
└── __init__.py          # Экспорт компонентов
```

## Спецификация компонентов

### 1. ChatRequestValidator (src/services/chat/validator.py)

```python
"""
Валидация чат-запросов и проверка прав доступа
"""
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status

from ..core.config_manager import ConfigManager
from ...logging.config import logger


class ChatRequestValidator:
    """Валидация чат-запросов и проверка прав доступа"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
    
    def validate_request(
        self, 
        requested_model: str, 
        allowed_models: list, 
        api_key: str, 
        project_name: str,
        request_id: str,
        user_id: str
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        """
        Валидирует запрос и возвращает конфигурацию модели
        
        Args:
            requested_model: Запрошенная модель
            allowed_models: Список разрешенных моделей
            api_key: API ключ
            project_name: Имя проекта
            request_id: ID запроса
            user_id: ID пользователя
            
        Returns:
            Tuple[model_config, provider_name, provider_model_name, provider_config]
            
        Raises:
            HTTPException: При ошибках валидации
        """
        # Валидация наличия модели
        if not requested_model:
            error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
            logger.error("Model not specified in request", extra={
                "detail": error_detail, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail,
            )

        # Проверка доступа к модели
        if allowed_models and requested_model not in allowed_models:
            error_detail = {"error": {"message": f"Model '{requested_model}' not allowed for this API key", "code": "model_not_allowed"}}
            logger.error(f"Model '{requested_model}' not allowed for API key", extra={
                "detail": error_detail, 
                "api_key": api_key, 
                "project_name": project_name, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_detail,
            )

        # Получение конфигурации модели
        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        
        if not model_config:
            error_detail = {"error": {"message": f"Model '{requested_model}' not found in configuration", "code": "model_not_found"}}
            logger.error(f"Model '{requested_model}' not found in configuration", extra={
                "detail": error_detail, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
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
            logger.error(f"Provider '{provider_name}' for model '{requested_model}' not found", extra={
                "detail": error_detail, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
            
        return model_config, provider_name, provider_model_name, provider_config
```

### 2. StreamBufferManager (src/services/chat/buffer_manager.py)

```python
"""
Управление буферами стриминга и UTF-8 обработкой
"""
import codecs
from typing import List


class StreamBufferManager:
    """Управление буферами стриминга и UTF-8 обработкой"""
    
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        """
        Инициализация менеджера буферов
        
        Args:
            max_buffer_size: Максимальный размер буфера в байтах
        """
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
        self.sse_buffer = ""
        self.json_buffer = ""
    
    def process_chunk(self, chunk: bytes) -> str:
        """
        Обрабатывает новый чанк и возвращает декодированную строку
        
        Args:
            chunk: Новый чанк данных
            
        Returns:
            Декодированная строка
        """
        # Используем incremental decoder для обработки UTF-8 границ
        decoded_chunk = self.utf8_decoder.decode(chunk, final=False)
        
        # Если decoded_chunk пустой, значит чанк был частью многобайтного символа
        if not decoded_chunk:
            return ""
        
        return decoded_chunk
    
    def get_sse_events(self) -> List[str]:
        """
        Возвращает полные SSE события из буфера
        
        Returns:
            Список полных SSE событий
        """
        events = []
        
        # SSE события разделены двойным переносом строки
        while '\n\n' in self.sse_buffer:
            event, self.sse_buffer = self.sse_buffer.split('\n\n', 1)
            if event.strip():
                events.append(event)
        
        return events
    
    def get_json_lines(self) -> List[str]:
        """
        Возвращает полные JSON строки из буфера
        
        Returns:
            Список полных JSON строк
        """
        lines = self.json_buffer.split('\n')
        self.json_buffer = lines[-1]  # Сохраняем неполную строку
        
        return [line for line in lines[:-1] if line.strip()]
    
    def add_to_sse_buffer(self, data: str):
        """
        Добавляет данные в SSE буфер с проверкой переполнения
        
        Args:
            data: Данные для добавления
        """
        if len(self.sse_buffer) + len(data) > self.max_buffer_size:
            # Очищаем половину буфера при переполнении
            self.sse_buffer = self.sse_buffer[len(self.sse_buffer)//2:]
        
        self.sse_buffer += data
    
    def add_to_json_buffer(self, data: str):
        """
        Добавляет данные в JSON буфер с проверкой переполнения
        
        Args:
            data: Данные для добавления
        """
        if len(self.json_buffer) + len(data) > self.max_buffer_size:
            # Очищаем половину буфера при переполнении
            self.json_buffer = self.json_buffer[len(self.json_buffer)//2:]
        
        self.json_buffer += data
    
    def clear_buffers(self):
        """Очищает все буферы"""
        self.sse_buffer = ""
        self.json_buffer = ""
        # Сбрасываем декодер
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
    
    def get_remaining_data(self) -> tuple:
        """
        Возвращает оставшиеся данные в буферах
        
        Returns:
            Tuple[sse_buffer, json_buffer]
        """
        return self.sse_buffer, self.json_buffer
```

### 3. StreamFormatProcessor (src/services/chat/format_processor.py)

```python
"""
Преобразование форматов стриминга (SSE/NDJSON)
"""
import json
import time
from typing import Dict, Any, Tuple


class StreamFormatProcessor:
    """Преобразование форматов стриминга (SSE/NDJSON)"""
    
    def detect_format(self, data: str) -> str:
        """
        Определяет формат стриминга
        
        Args:
            data: Данные для анализа
            
        Returns:
            'sse' или 'ndjson'
        """
        if 'data:' in data or data.startswith(':'):
            return 'sse'
        else:
            return 'ndjson'
    
    def process_sse_event(self, event: str, full_content: str, usage: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Обрабатывает SSE событие
        
        Args:
            event: SSE событие
            full_content: Текущий полный контент
            usage: Текущие данные об использовании
            
        Returns:
            Tuple[updated_full_content, updated_usage]
        """
        for line in event.split('\n'):
            line = line.strip()
            
            # Пропускаем SSE комментарии
            if line.startswith(':'):
                continue
            
            if line.startswith('data: '):
                json_data = line[6:].strip()  # Удаляем 'data: ' префикс
                if json_data == '[DONE]':
                    continue
                    
                try:
                    data = json.loads(json_data)
                    
                    # Обработка ошибок в SSE данных
                    if 'error' in data:
                        continue
                    
                    # Извлечение контента
                    if 'choices' in data and len(data['choices']) > 0:
                        delta_content = data['choices'][0].get('delta', {}).get('content')
                        if delta_content:
                            full_content += delta_content
                    
                    # Извлечение данных об использовании
                    if 'usage' in data:
                        usage = data['usage']
                        
                except json.JSONDecodeError:
                    # Пропускаем невалидный JSON
                    pass
                    
        return full_content, usage
    
    def process_ndjson_line(self, line: str, model_id: str, request_id: str) -> Tuple[bytes, str, Dict[str, Any]]:
        """
        Обрабатывает NDJSON строку и возвращает OpenAI формат
        
        Args:
            line: NDJSON строка
            model_id: ID модели
            request_id: ID запроса
            
        Returns:
            Tuple[openai_chunk_bytes, content, usage]
        """
        processed_chunk = b""
        content = ""
        usage = {}
        
        try:
            data = json.loads(line)
            
            # Проверка завершения
            if data.get('done'):
                if 'prompt_eval_count' in data:
                    usage = {
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0)
                    }
                elif 'usage' in data:
                    usage = data['usage']
                    
                return processed_chunk, content, usage
            
            # Извлечение контента
            delta_content = data.get('message', {}).get('content', '')
            if delta_content:
                content = delta_content
            
            # Формирование OpenAI совместимого чанка
            openai_chunk = {
                "id": f"chatcmpl-{request_id}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": delta_content},
                        "logprobs": None,
                        "finish_reason": None
                    }
                ]
            }
            
            processed_chunk = f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
            
        except json.JSONDecodeError:
            # Возвращаем пустой результат при ошибке
            pass
            
        return processed_chunk, content, usage
```

### 4. StreamingErrorHandler (src/services/chat/error_handler.py)

```python
"""
Обработка ошибок стриминга
"""
import json
from typing import Dict, Any
from fastapi import status

from ...core.exceptions import ProviderStreamError, ProviderNetworkError
from ...logging.config import logger


class StreamingErrorHandler:
    """Обработка ошибок стриминга"""
    
    def format_sse_error(self, message: str, code: str, status_code: int) -> bytes:
        """
        Форматирует ошибку в SSE формате
        
        Args:
            message: Сообщение об ошибке
            code: Код ошибки
            status_code: HTTP статус код
            
        Returns:
            Отформатированная ошибка в SSE формате
        """
        error_payload = {
            "error": {
                "message": message,
                "type": "api_error",
                "code": code,
                "param": None
            }
        }
        return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
    
    def handle_streaming_error(self, error: Exception, request_id: str, user_id: str) -> bytes:
        """
        Обрабатывает ошибку стриминга и возвращает форматированный ответ
        
        Args:
            error: Исключение
            request_id: ID запроса
            user_id: ID пользователя
            
        Returns:
            Отформатированная ошибка в SSE формате
        """
        if isinstance(error, ProviderStreamError):
            logger.error(
                f"ProviderStreamError in stream for request {request_id}: {error.message}", 
                extra={
                    "request_id": request_id, 
                    "user_id": user_id, 
                    "log_type": "error", 
                    "status_code": error.status_code, 
                    "error_code": error.error_code, 
                    "original_exception": str(error.original_exception)
                }
            )
            return self.format_sse_error(error.message, error.error_code, error.status_code)
            
        elif isinstance(error, ProviderNetworkError):
            logger.error(
                f"ProviderNetworkError in stream for request {request_id}: {error.message}", 
                extra={
                    "request_id": request_id, 
                    "user_id": user_id, 
                    "log_type": "error", 
                    "original_exception": str(error.original_exception)
                }
            )
            return self.format_sse_error(error.message, "provider_network_error", status.HTTP_503_SERVICE_UNAVAILABLE)
            
        else:
            logger.error(
                f"Unexpected error in stream for request {request_id}: {error}", 
                extra={
                    "request_id": request_id, 
                    "user_id": user_id, 
                    "log_type": "error", 
                    "exception": str(error)
                }, 
                exc_info=True
            )
            return self.format_sse_error(
                f"An unexpected error occurred during streaming: {error}", 
                "unexpected_streaming_error", 
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )
```

### 5. ChatLogger (src/services/chat/logger.py)

```python
"""
Логирование чат-операций
"""
from typing import Dict, Any
from fastapi import HTTPException, status

from ...logging.config import logger


class ChatLogger:
    """Логирование всех чат-операций"""
    
    def log_request(self, request_id: str, user_id: str, model_id: str, request_body: Dict[str, Any]):
        """
        Логирует входящий запрос
        
        Args:
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
            request_body: Тело запроса
        """
        logger.info(
            "Chat Completion Request",
            extra={
                "log_type": "request",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": model_id,
                "request_body_summary": {
                    "model": model_id,
                    "messages_count": len(request_body.get("messages", [])),
                    "first_message_content": request_body.get("messages", [{}])[0].get("content") if request_body.get("messages") else None
                }
            }
        )
    
    def log_response(self, request_id: str, user_id: str, model_id: str, response_data: Dict[str, Any]):
        """
        Логирует ответ
        
        Args:
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
            response_data: Данные ответа
        """
        usage = response_data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        logger.info(
            "Chat Completion Response",
            extra={
                "log_type": "response",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": model_id,
                "http_status_code": status.HTTP_200_OK,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_body_summary": {
                    "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                    "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                }
            }
        )
    
    def log_streaming_completion(self, request_id: str, user_id: str, model_id: str, 
                               content: str, usage: Dict[str, Any]):
        """
        Логирует завершение стриминга
        
        Args:
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
            content: Полный контент
            usage: Данные об использовании
        """
        prompt_tokens = usage.get("prompt_tokens", 0) if usage else 0
        completion_tokens = usage.get("completion_tokens", 0) if usage else 0

        logger.info(
            "Chat Completion Response",
            extra={
                "log_type": "response",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": model_id,
                "http_status_code": status.HTTP_200_OK,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_body_summary": {
                    "finish_reason": "stop",
                    "content_preview": content
                }
            }
        )
    
    def log_error(self, error: Exception, request_id: str, user_id: str, model_id: str):
        """
        Логирует ошибку
        
        Args:
            error: Исключение
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
        """
        if isinstance(error, HTTPException):
            logger.error(
                f"HTTPException from provider: {error.detail.get('error', {}).get('message', str(error))}",
                extra={
                    "status_code": error.status_code,
                    "detail": error.detail,
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": model_id,
                    "log_type": "error"
                }
            )
        else:
            logger.error(
                f"An unexpected error occurred: {error}",
                extra={
                    "detail": {"error": {"message": f"An unexpected error occurred: {error}", "code": "unexpected_error"}},
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": model_id,
                    "log_type": "error"
                },
                exc_info=True
            )
```

### 6. StreamingHandler (src/services/chat/streaming_handler.py)

```python
"""
Координация обработки стриминга
"""
import json
from typing import AsyncGenerator

from fastapi import status

from .buffer_manager import StreamBufferManager
from .format_processor import StreamFormatProcessor
from .error_handler import StreamingErrorHandler
from .logger import ChatLogger
from ...logging.config import logger


class StreamingHandler:
    """Координация обработки стриминга"""
    
    def __init__(self, buffer_manager: StreamBufferManager, 
                 format_processor: StreamFormatProcessor,
                 error_handler: StreamingErrorHandler,
                 chat_logger: ChatLogger):
        self.buffer_manager = buffer_manager
        self.format_processor = format_processor
        self.error_handler = error_handler
        self.logger = chat_logger
    
    async def handle_stream(self, response_data, provider_type: str, model_id: str,
                          request_id: str, user_id: str) -> AsyncGenerator[bytes, None]:
        """
        Основной метод обработки стриминга
        
        Args:
            response_data: Ответ от провайдера
            provider_type: Тип провайдера
            model_id: ID модели
            request_id: ID запроса
            user_id: ID пользователя
            
        Yields:
            Чанки данных в SSE формате
        """
        full_content = ""
        stream_completed_usage = None
        stream_has_error = False
        stream_format = None
        first_chunk = True
        
        try:
            async for chunk in response_data.body_iterator:
                try:
                    # Обработка чанка
                    decoded_chunk = self.buffer_manager.process_chunk(chunk)
                    
                    if not decoded_chunk:
                        continue
                    
                    # Определение формата при первом чанке
                    if first_chunk:
                        first_chunk = False
                        stream_format = self.format_processor.detect_format(decoded_chunk)
                        logger.info(f"Auto-detected {stream_format} format for request {request_id}",
                                  extra={"request_id": request_id, "provider_type": provider_type})
                    
                    # Обработка в зависимости от формата
                    if stream_format == 'ndjson':
                        self.buffer_manager.add_to_json_buffer(decoded_chunk)
                        lines = self.buffer_manager.get_json_lines()
                        
                        for line in lines:
                            processed_chunk, content, usage = self.format_processor.process_ndjson_line(
                                line, model_id, request_id
                            )
                            if content:
                                full_content += content
                            if usage:
                                stream_completed_usage = usage
                            if processed_chunk:
                                yield processed_chunk
                                
                    elif stream_format == 'sse':
                        self.buffer_manager.add_to_sse_buffer(decoded_chunk)
                        events = self.buffer_manager.get_sse_events()
                        
                        for event in events:
                            full_content, stream_completed_usage = self.format_processor.process_sse_event(
                                event, full_content, stream_completed_usage
                            )
                            # Отправляем событие с правильным SSE форматированием
                            yield f"{event}\n\n".encode('utf-8')
                    
                except Exception as e:
                    error_chunk = self.error_handler.handle_streaming_error(e, request_id, user_id)
                    yield error_chunk
                    stream_has_error = True
                    break
                    
        except Exception as e:
            logger.error(f"Critical error before stream iteration for request {request_id}: {e}", 
                        extra={"request_id": request_id, "user_id": user_id, "log_type": "error"}, 
                        exc_info=True)
            error_chunk = self.error_handler.handle_streaming_error(e, request_id, user_id)
            yield error_chunk
            stream_has_error = True
        
        # Обработка оставшихся данных в буферах
        if not stream_has_error:
            sse_buffer, json_buffer = self.buffer_manager.get_remaining_data()
            
            if stream_format == 'sse' and sse_buffer.strip():
                full_content, stream_completed_usage = self.format_processor.process_sse_event(
                    sse_buffer, full_content, stream_completed_usage
                )
                yield f"{sse_buffer}\n\n".encode('utf-8')
            elif stream_format == 'ndjson' and json_buffer.strip():
                try:
                    processed_chunk, content, usage = self.format_processor.process_ndjson_line(
                        json_buffer, model_id, request_id
                    )
                    if content:
                        full_content += content
                    if usage:
                        stream_completed_usage = usage
                    if processed_chunk:
                        yield processed_chunk
                except:
                    pass  # Игнорируем ошибки в финальной обработке буфера
            
            # Логирование завершения
            self.logger.log_streaming_completion(request_id, user_id, model_id, full_content, stream_completed_usage)
            yield b"data: [DONE]\n\n"
        else:
            logger.warning(f"Stream terminated with error for request {request_id}, skipping [DONE]",
                         extra={"request_id": request_id, "user_id": user_id, "log_type": "warning"})
        
        # Очистка буферов
        self.buffer_manager.clear_buffers()
```

### 7. Обновленный ChatService (src/services/chat_service.py)

```python
"""
Обновленный ChatService после рефакторинга
"""
import httpx
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from .model_service import ModelService
from .chat.validator import ChatRequestValidator
from .chat.buffer_manager import StreamBufferManager
from .chat.format_processor import StreamFormatProcessor
from .chat.error_handler import StreamingErrorHandler
from .chat.logger import ChatLogger
from .chat.streaming_handler import StreamingHandler


class ChatService:
    """Координация компонентов обработки чат-запросов"""
    
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.httpx_client = httpx_client
        self.model_service = model_service
        
        # Инициализация компонентов
        self.validator = ChatRequestValidator(config_manager)
        self.buffer_manager = StreamBufferManager()
        self.format_processor = StreamFormatProcessor()
        self.error_handler = StreamingErrorHandler()
        self.logger = ChatLogger()
        self.streaming_handler = StreamingHandler(
            self.buffer_manager, 
            self.format_processor, 
            self.error_handler, 
            self.logger
        )
    
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
        self.logger.log_request(request_id, user_id, requested_model, request_body)

        # Валидация
        model_config, provider_name, provider_model_name, provider_config = \
            self.validator.validate_request(
                requested_model, allowed_models, api_key, project_name, request_id, user_id
            )

        # Получение провайдера
        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            error_detail = {"error": {"message": f"Provider configuration error: {e}", "code": "provider_config_error"}}
            self.logger.log_error(Exception(f"Provider configuration error: {e}"), request_id, user_id, requested_model)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
        
        try:
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            if isinstance(response_data, StreamingResponse):
                return StreamingResponse(
                    self.streaming_handler.handle_stream(
                        response_data, provider_config.get("type"), requested_model, request_id, user_id
                    ), 
                    media_type=response_data.media_type
                )
            else:
                self.logger.log_response(request_id, user_id, requested_model, response_data)
                return JSONResponse(content=response_data)
            
        except HTTPException as e:
            self.logger.log_error(e, request_id, user_id, requested_model)
            raise e
        except Exception as e:
            self.logger.log_error(e, request_id, user_id, requested_model)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}},
            )
```

### 8. Обновление __init__.py для экспорта компонентов (src/services/chat/__init__.py)

```python
"""
Экспорт компонентов чат-сервиса
"""

from .validator import ChatRequestValidator
from .buffer_manager import StreamBufferManager
from .format_processor import StreamFormatProcessor
from .error_handler import StreamingErrorHandler
from .logger import ChatLogger
from .streaming_handler import StreamingHandler

__all__ = [
    'ChatRequestValidator',
    'StreamBufferManager',
    'StreamFormatProcessor',
    'StreamingErrorHandler',
    'ChatLogger',
    'StreamingHandler'
]
```

## Порядок реализации

1. Создать директорию `src/services/chat/`
2. Создать файл `__init__.py`
3. Создать `validator.py` - ChatRequestValidator
4. Создать `buffer_manager.py` - StreamBufferManager
5. Создать `format_processor.py` - StreamFormatProcessor
6. Создать `error_handler.py` - StreamingErrorHandler
7. Создать `logger.py` - ChatLogger
8. Создать `streaming_handler.py` - StreamingHandler
9. Обновить `chat_service.py` с новыми компонентами
10. Обновить `__init__.py` для экспорта
11. Запустить тесты для проверки функциональности

## Тестирование

После реализации необходимо запустить существующие тесты:

```bash
python tests/test_models.py
python tests/test_streaming_fixes.py
```

## Ожидаемые результаты

- ChatService сокращается с 431 строки до ~100 строк
- Каждая компонента имеет четкую ответственность
- Улучшается тестируемость и поддерживаемость
- Сохраняется вся существующая функциональность