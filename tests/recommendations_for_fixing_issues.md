# Рекомендации по исправлению проблем с 500 ошибками

## Обзор

На основе детального анализа кода и failing тестов, подготовлены комплексные рекомендации по исправлению проблем, приводящих к 500 ошибкам вместо корректных кодов состояния HTTP.

## Приоритеты исправлений

### 🔴 Высокий приоритет (критические проблемы)
1. Внедрение валидации входных данных на уровне API
2. Исправление обработки ошибок в сервисах
3. Нормализация кодов состояния HTTP

### 🟡 Средний приоритет (важные улучшения)
1. Улучшение обработки ошибок в провайдерах
2. Внедрение централизованной обработки ошибок
3. Улучшение логирования ошибок

### 🟢 Низкий приоритет (оптимизации)
1. Улучшение сообщений об ошибках
2. Внедрение Pydantic моделей для валидации
3. Улучшение документации API

## Детальные рекомендации

### 1. Внедрение валидации входных данных на уровне API

#### Проблема:
Отсутствие первичной валидации входных данных в эндпоинтах API.

#### Решение:
Добавить валидацию входных данных перед передачей в сервисы.

#### Пример реализации для Chat Completions:

```python
# src/api/validation.py
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Any, Dict
from fastapi import HTTPException, status

class MessageModel(BaseModel):
    role: str
    content: str
    
    @validator('role')
    def validate_role(cls, v):
        if v not in ['system', 'user', 'assistant']:
            raise ValueError(f"Invalid role: {v}")
        return v

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[MessageModel]
    stream: bool = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    
    @validator('messages')
    def validate_messages(cls, v):
        if not v:
            raise ValueError("Messages cannot be empty")
        return v

# src/api/main.py
from .validation import ChatCompletionRequest

@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/v1/chat/completions"))
):
    try:
        # Валидация входных данных
        request_body = await request.json()
        validated_request = ChatCompletionRequest(**request_body)
        
        # Передача валидированных данных в сервис
        return await app.state.chat_service.chat_completions(validated_request.dict(), auth_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"message": str(e), "code": "validation_error"}}
        )
```

#### Пример реализации для Embeddings:

```python
# src/api/validation.py
class EmbeddingRequest(BaseModel):
    model: str
    input: List[str]
    encoding_format: str = "float"
    
    @validator('input')
    def validate_input(cls, v):
        if not v:
            raise ValueError("Input cannot be empty")
        if not all(isinstance(item, str) for item in v):
            raise ValueError("All input items must be strings")
        return v

# src/api/main.py
@app.post("/v1/embeddings")
async def create_embeddings(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/v1/embeddings"))
):
    try:
        request_body = await request.json()
        validated_request = EmbeddingRequest(**request_body)
        
        return await app.state.embedding_service.create_embeddings(validated_request.dict(), auth_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"message": str(e), "code": "validation_error"}}
        )
```

### 2. Исправление обработки ошибок в сервисах

#### Проблема:
Все исключения в сервисах обрабатываются как "неожиданные" и возвращают 500 ошибку.

#### Решение:
Добавить дифференцированную обработку различных типов исключений.

#### Пример реализации для Chat Service:

```python
# src/services/chat_service/chat_service.py
from fastapi import HTTPException, status
from pydantic import ValidationError

class ChatService:
    async def chat_completions(self, request_body: Dict[str, Any], auth_data: Tuple[str, str, list, list]) -> Any:
        try:
            # Существующая логика
            pass
        except ValidationError as e:
            # Ошибки валидации данных
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"message": f"Validation error: {e}", "code": "validation_error"}}
            )
        except KeyError as e:
            # Отсутствие обязательных полей
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"message": f"Missing required field: {e}", "code": "missing_field"}}
            )
        except ValueError as e:
            # Неверные значения полей
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": {"message": f"Invalid field value: {e}", "code": "invalid_field_value"}}
            )
        except HTTPException as e:
            # HTTP исключения пробрасываем как есть
            raise e
        except Exception as e:
            # Только действительно неожиданные ошибки приводят к 500
            logger.error(f"Unexpected error in chat_completions: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": "Internal server error", "code": "internal_server_error"}}
            )
```

### 3. Нормализация кодов состояния HTTP

#### Проблема:
Внешние API возвращают 422 ошибки, но сервис не преобразует их в 400.

#### Решение:
Добавить маппинг кодов состояния от внешних API к корректным кодам для клиентов.

#### Пример реализации:

```python
# src/core/error_mapping.py
from httpx import HTTPStatusError

class ErrorMapper:
    @staticmethod
    def map_provider_error(status_code: int, error_message: str) -> tuple:
        """
        Преобразует код ошибки от провайдера в корректный код для клиента
        
        Returns:
            tuple: (status_code, error_detail)
        """
        # Ошибки валидации от провайдера преобразуем в 400
        if status_code == 422:
            return 400, {"error": {"message": error_message, "code": "validation_error"}}
        
        # Ошибки аутентификации от провайдера
        if status_code == 401:
            return 401, {"error": {"message": "Provider authentication failed", "code": "provider_auth_error"}}
        
        # Ошибки доступа от провайдера
        if status_code == 403:
            return 403, {"error": {"message": "Provider access denied", "code": "provider_access_denied"}}
        
        # Модель не найдена у провайдера
        if status_code == 404:
            return 404, {"error": {"message": "Model not found", "code": "model_not_found"}}
        
        # Слишком большой запрос
        if status_code == 413:
            return 413, {"error": {"message": "Request too large", "code": "request_too_large"}}
        
        # Лимит превышен
        if status_code == 429:
            return 429, {"error": {"message": "Rate limit exceeded", "code": "rate_limit_exceeded"}}
        
        # Серверные ошибки провайдера
        if status_code >= 500:
            return 502, {"error": {"message": "Provider server error", "code": "provider_server_error"}}
        
        # Другие клиентские ошибки
        if 400 <= status_code < 500:
            return 400, {"error": {"message": error_message, "code": f"provider_error_{status_code}"}}
        
        # Неизвестные ошибки
        return 500, {"error": {"message": "Unknown provider error", "code": "unknown_provider_error"}}

# src/providers/openai.py
from ..core.error_mapping import ErrorMapper

async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
    try:
        # Существующая логика
        pass
    except httpx.HTTPStatusError as e:
        # Преобразуем ошибки провайдера в корректные коды
        mapped_status, error_detail = ErrorMapper.map_provider_error(
            e.response.status_code, 
            f"Provider error: {e.response.text}"
        )
        raise HTTPException(status_code=mapped_status, detail=error_detail)
```

### 4. Внедрение централизованной обработки ошибок

#### Проблема:
Каждый сервис и провайдер обрабатывают ошибки по-своему.

#### Решение:
Создать централизованный обработчик ошибок.

#### Пример реализации:

```python
# src/core/error_handler.py
from fastapi import HTTPException, status
from typing import Any, Dict
import logging

logger = logging.getLogger("nnp-llm-router")

class ErrorHandler:
    @staticmethod
    def handle_validation_error(error: Exception, context: Dict[str, Any] = None) -> HTTPException:
        """Обработка ошибок валидации"""
        error_detail = {
            "error": {
                "message": str(error),
                "code": "validation_error",
                "context": context or {}
            }
        }
        logger.warning(f"Validation error: {error}", extra={"error_detail": error_detail})
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail
        )
    
    @staticmethod
    def handle_provider_error(error: Exception, context: Dict[str, Any] = None) -> HTTPException:
        """Обработка ошибок провайдера"""
        error_detail = {
            "error": {
                "message": str(error),
                "code": "provider_error",
                "context": context or {}
            }
        }
        logger.error(f"Provider error: {error}", extra={"error_detail": error_detail})
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=error_detail
        )
    
    @staticmethod
    def handle_unexpected_error(error: Exception, context: Dict[str, Any] = None) -> HTTPException:
        """Обработка неожиданных ошибок"""
        error_detail = {
            "error": {
                "message": "Internal server error",
                "code": "internal_server_error"
            }
        }
        logger.error(f"Unexpected error: {error}", extra={"error_detail": error_detail}, exc_info=True)
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail
        )

# src/services/chat_service/chat_service.py
from ..core.error_handler import ErrorHandler

class ChatService:
    async def chat_completions(self, request_body: Dict[str, Any], auth_data: Tuple[str, str, list, list]) -> Any:
        try:
            # Существующая логика
            pass
        except ValidationError as e:
            raise ErrorHandler.handle_validation_error(e, {"service": "chat_completions"})
        except ProviderAPIError as e:
            raise ErrorHandler.handle_provider_error(e, {"service": "chat_completions"})
        except Exception as e:
            raise ErrorHandler.handle_unexpected_error(e, {"service": "chat_completions"})
```

### 5. Улучшение обработки ошибок в провайдерах

#### Проблема:
Провайдеры не выполняют должную валидацию входных данных.

#### Решение:
Добавить валидацию в провайдерах перед отправкой запросов.

#### Пример реализации:

```python
# src/providers/openai.py
async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
    # Валидация входных данных
    if "input" not in request_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"message": "Missing required field: input", "code": "missing_field"}}
        )
    
    input_data = request_body["input"]
    if not input_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"message": "Input cannot be empty", "code": "empty_input"}}
        )
    
    # Проверка размера входных данных
    if isinstance(input_data, list) and len(input_data) > 1000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": {"message": "Input too large (max 1000 items)", "code": "input_too_large"}}
        )
    
    # Существующая логика
    pass

async def transcriptions(
    self,
    audio_data: bytes,
    filename: str,
    content_type: str,
    model_id: str,
    **kwargs
) -> Dict[str, Any]:
    # Валидация входных данных
    if not audio_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"message": "Audio file cannot be empty", "code": "empty_file"}}
        )
    
    # Проверка размера файла (например, 25MB максимум)
    max_file_size = 25 * 1024 * 1024  # 25MB
    if len(audio_data) > max_file_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": {"message": "Audio file too large (max 25MB)", "code": "file_too_large"}}
        )
    
    # Существующая логика
    pass
```

### 6. Улучшение middleware для обработки ошибок

#### Проблема:
Middleware не обрабатывает все типы исключений.

#### Решение:
Улучшить middleware для централизованной обработки ошибок.

#### Пример реализации:

```python
# src/api/middleware.py
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import logging

logger = logging.getLogger("nnp-llm-router")

class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except HTTPException as e:
            # HTTP исключения обрабатываем как есть
            return JSONResponse(
                status_code=e.status_code,
                content=e.detail
            )
        except ValueError as e:
            # Ошибки валидации
            logger.warning(f"Validation error: {e}", extra={"request_id": getattr(request.state, 'request_id', None)})
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": {"message": str(e), "code": "validation_error"}}
            )
        except Exception as e:
            # Неожиданные ошибки
            request_id = getattr(request.state, 'request_id', None)
            logger.error(f"Unexpected error: {e}", extra={"request_id": request_id}, exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": {"message": "Internal server error", "code": "internal_server_error"}}
            )

# src/api/main.py
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(RequestLoggerMiddleware)
```

## План внедрения

### Этап 1: Критические исправления (1-2 дня)
1. Добавить базовую валидацию в эндпоинты API
2. Исправить обработку ошибок в сервисах
3. Добавить маппинг кодов состояния от провайдеров

### Этап 2: Улучшения (2-3 дня)
1. Внедрить централизованный обработчик ошибок
2. Улучшить валидацию в провайдерах
3. Обновить middleware для обработки ошибок

### Этап 3: Оптимизации (1-2 дня)
1. Внедрить Pydantic модели для валидации
2. Улучшить сообщения об ошибках
3. Обновить тесты для проверки исправлений

## Ожидаемые результаты

1. **Снижение 500 ошибок**: Предсказуемые ошибки валидации будут возвращать корректные коды состояния
2. **Улучшение пользовательского опыта**: Клиенты будут получать понятные сообщения об ошибках
3. **Упрощение отладки**: Лучшее логирование и структурированные ошибки
4. **Соответствие REST принципам**: Правильные коды состояния HTTP для различных типов ошибок
5. **Стабильность сервиса**: Уменьшение падений на предсказуемых ошибках

## Тестирование исправлений

После внедрения изменений необходимо:

1. Запустить failing тесты и убедиться, что они проходят
2. Добавить новые тесты для проверки сценариев валидации
3. Провести нагрузочное тестирование для проверки обработки ошибок
4. Проверить логирование ошибок в различных сценариях

## Заключение

Предложенные рекомендации позволят решить основную проблему 500 ошибок путем внедрения комплексного подхода к валидации данных и обработке ошибок на всех уровнях архитектуры приложения. Это значительно улучшит стабильность и предсказуемость работы сервиса.