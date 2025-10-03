# План рефакторинга ChatService

## Обзор

**Текущая проблема:** [`ChatService`](src/services/chat_service.py) (431 строка) нарушает принцип единственной ответственности (SRP), обрабатывая множество различных задач:
- Валидация запросов
- Обработка стриминга
- Преобразование форматов
- Логирование операций
- Буферизация UTF-8
- Обработка SSE/NDJSON событий
- Управление ошибками стриминга

**Цель рефакторинга:** Разделить ChatService на специализированные компоненты, каждый из которых отвечает за одну конкретную задачу.

## Анализ текущего ChatService

### Текущие ответственности

```python
class ChatService:
    # 1. Валидация запросов (строки 106-144)
    def _validate_request_and_model(...)
    
    # 2. Получение провайдера (строки 146-155)
    def _get_provider_instance(...)
    
    # 3. Основная логика обработки (строки 22-88)
    async def chat_completions(...)
    
    # 4. Обработка стриминга (строки 157-277)
    async def _stream_response_handler(...)
    
    # 5. Обработка SSE событий (строки 278-308)
    def _process_openai_sse_event(...)
    
    # 6. Обработка Ollama строк (строки 310-346)
    def _process_ollama_line(...)
    
    # 7. Логирование запросов (строки 90-104)
    def _log_chat_completion_request(...)
    
    # 8. Логирование ответов (строки 385-405)
    def _log_non_streaming_response(...)
    
    # 9. Логирование стриминга (строки 348-368)
    def _log_streaming_completion(...)
    
    # 10. Форматирование ошибок (строки 370-383)
    def _format_sse_error(...)
    
    # 11. Логирование исключений (строки 407-431)
    def _log_http_exception(...)
    def _log_unexpected_exception(...)
```

### Проблемы текущей реализации

1. **Слишком много ответственностей** - один класс делает всё
2. **Сложность тестирования** - трудно изолировать отдельные функции
3. **Сложность поддержки** - изменения в одной области могут затронуть другие
4. **Низкая переиспользуемость** - компоненты нельзя использовать независимо
5. **Сложность понимания** - 431 строка кода в одном классе

## Предлагаемая архитектура

### Новая структура компонентов

```python
# 1. Валидация запросов
class ChatRequestValidator:
    """Валидация чат-запросов и проверка прав доступа"""

# 2. Обработка стриминга
class StreamingHandler:
    """Обработка стриминговых ответов от провайдеров"""

# 3. Преобразование форматов
class StreamFormatProcessor:
    """Преобразование форматов стриминга (SSE/NDJSON)"""

# 4. Управление буферами
class StreamBufferManager:
    """Управление буферами стриминга и UTF-8 обработкой"""

# 5. Логирование чат-операций
class ChatLogger:
    """Логирование всех чат-операций"""

# 6. Обработка ошибок стриминга
class StreamingErrorHandler:
    """Обработка ошибок в стриминговых ответах"""

# 7. Основной сервис (координатор)
class ChatService:
    """Координация компонентов обработки чат-запросов"""
```

## Детальный план рефакторинга

### Этап 1: Подготовка и анализ (1 день)

**Задачи:**
1. Создать ветку `refactor/chat-service`
2. Проанализировать зависимости между методами
3. Определить интерфейсы между компонентами
4. Создать тесты для текущей функциональности

**Результат:**
- Ветка для рефакторинга
- Карта зависимостей методов
- Базовые тесты
- Определенные интерфейсы

### Этап 2: Создание компонентов (2-3 дня)

#### 2.1 ChatRequestValidator

**Ответственность:**
- Валидация входящих запросов
- Проверка прав доступа к моделям
- Проверка конфигурации провайдеров

**Интерфейс:**
```python
class ChatRequestValidator:
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
        
        Returns:
            Tuple[model_config, provider_name, provider_model_name, provider_config]
        
        Raises:
            HTTPException: При ошибках валидации
        """
```

**Методы для переноса:**
- `_validate_request_and_model` (строки 106-144)
- `_get_provider_instance` (строки 146-155)

#### 2.2 StreamBufferManager

**Ответственность:**
- Управление UTF-8 буферизацией
- Управление буферами SSE/JSON
- Предотвращение переполнения буферов

**Интерфейс:**
```python
class StreamBufferManager:
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
        self.sse_buffer = ""
        self.json_buffer = ""
    
    def process_chunk(self, chunk: bytes) -> str:
        """Обрабатывает новый чанк и возвращает декодированную строку"""
    
    def get_sse_events(self) -> List[str]:
        """Возвращает полные SSE события из буфера"""
    
    def get_json_lines(self) -> List[str]:
        """Возвращает полные JSON строки из буфера"""
    
    def clear_buffers(self):
        """Очищает все буферы"""
```

**Методы для переноса:**
- Логика UTF-8 декодирования (строки 161-183)
- Управление буферами (строки 164-166, 200-203, 213-223)

#### 2.3 StreamFormatProcessor

**Ответственность:**
- Определение формата стриминга (SSE/NDJSON)
- Обработка SSE событий
- Обработка NDJSON строк
- Преобразование в OpenAI формат

**Интерфейс:**
```python
class StreamFormatProcessor:
    def detect_format(self, data: str) -> str:
        """Определяет формат стриминга"""
    
    def process_sse_event(self, event: str, full_content: str, usage: Dict) -> Tuple[str, Dict]:
        """Обрабатывает SSE событие"""
    
    def process_ndjson_line(self, line: str, model_id: str, request_id: str) -> Tuple[bytes, str, Dict]:
        """Обрабатывает NDJSON строку и возвращает OpenAI формат"""
```

**Методы для переноса:**
- `_process_openai_sse_event` (строки 278-308)
- `_process_ollama_line` (строки 310-346)
- Логика определения формата (строки 186-196)

#### 2.4 StreamingErrorHandler

**Ответственность:**
- Обработка ошибок стриминга
- Форматирование ошибок в SSE формате
- Логирование ошибок стриминга

**Интерфейс:**
```python
class StreamingErrorHandler:
    def format_sse_error(self, message: str, code: str, status_code: int) -> bytes:
        """Форматирует ошибку в SSE формате"""
    
    def handle_streaming_error(self, error: Exception, request_id: str, user_id: str) -> bytes:
        """Обрабатывает ошибку стриминга и возвращает форматированный ответ"""
```

**Методы для переноса:**
- `_format_sse_error` (строки 370-383)
- Логика обработки ошибок в стриминге (строки 228-247)

#### 2.5 ChatLogger

**Ответственность:**
- Логирование всех чат-операций
- Структурированное логирование запросов
- Логирование ответов и ошибок

**Интерфейс:**
```python
class ChatLogger:
    def log_request(self, request_id: str, user_id: str, model_id: str, request_body: Dict):
        """Логирует входящий запрос"""
    
    def log_response(self, request_id: str, user_id: str, model_id: str, response_data: Dict):
        """Логирует ответ"""
    
    def log_streaming_completion(self, request_id: str, user_id: str, model_id: str, 
                               content: str, usage: Dict):
        """Логирует завершение стриминга"""
    
    def log_error(self, error: Exception, request_id: str, user_id: str, model_id: str):
        """Логирует ошибку"""
```

**Методы для переноса:**
- `_log_chat_completion_request` (строки 90-104)
- `_log_non_streaming_response` (строки 385-405)
- `_log_streaming_completion` (строки 348-368)
- `_log_http_exception` (строки 407-418)
- `_log_unexpected_exception` (строки 420-431)

#### 2.6 StreamingHandler

**Ответственность:**
- Координация обработки стриминга
- Управление жизненным циклом стриминга
- Интеграция всех компонентов стриминга

**Интерфейс:**
```python
class StreamingHandler:
    def __init__(self, buffer_manager: StreamBufferManager, 
                 format_processor: StreamFormatProcessor,
                 error_handler: StreamingErrorHandler,
                 logger: ChatLogger):
        self.buffer_manager = buffer_manager
        self.format_processor = format_processor
        self.error_handler = error_handler
        self.logger = logger
    
    async def handle_stream(self, response_data: StreamingResponse, 
                          provider_type: str, model_id: str,
                          request_id: str, user_id: str) -> AsyncGenerator[bytes, None]:
        """Основной метод обработки стриминга"""
```

### Этап 3: Рефакторинг основного сервиса (2 дня)

#### 3.1 Новый ChatService

**Ответственность:**
- Координация всех компонентов
- Обработка нестриминговых запросов
- Управление жизненным циклом запроса

**Новая реализация:**
```python
class ChatService:
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
        """Основной метод обработки чат-запросов"""
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
        provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        
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
            
        except Exception as e:
            self.logger.log_error(e, request_id, user_id, requested_model)
            raise
```

### Этап 4: Тестирование и отладка (2-3 дня)

**Задачи:**
1. Создать unit тесты для каждого компонента
2. Создать integration тесты для ChatService
3. Протестировать все существующие сценарии
4. Проверить производительность

**Тесты для компонентов:**

```python
# test_chat_request_validator.py
class TestChatRequestValidator:
    def test_validate_request_success(self):
        # Тест успешной валидации
    
    def test_validate_model_not_allowed(self):
        # Тест запрета доступа к модели
    
    def test_validate_model_not_found(self):
        # Тест отсутствия модели

# test_stream_buffer_manager.py
class TestStreamBufferManager:
    def test_utf8_decoding(self):
        # Тест UTF-8 декодирования
    
    def test_buffer_overflow(self):
        # Тест переполнения буфера
    
    def test_sse_event_extraction(self):
        # Тест извлечения SSE событий

# test_stream_format_processor.py
class TestStreamFormatProcessor:
    def test_format_detection(self):
        # Тест определения формата
    
    def test_sse_processing(self):
        # Тест обработки SSE
    
    def test_ndjson_processing(self):
        # Тест обработки NDJSON
```

### Этап 5: Оптимизация и документация (1 день)

**Задачи:**
1. Оптимизировать производительность компонентов
2. Добавить документацию и docstrings
3. Обновить existing тесты
4. Создать примеры использования

## План миграции

### Шаг 1: Подготовка
```bash
# Создание ветки
git checkout -b refactor/chat-service

# Копирование текущего файла
cp src/services/chat_service.py src/services/chat_service_original.py
```

### Шаг 2: Создание новых компонентов
```bash
# Создание директории для компонентов
mkdir -p src/services/chat

# Создание файлов компонентов
touch src/services/chat/validator.py
touch src/services/chat/streaming_handler.py
touch src/services/chat/buffer_manager.py
touch src/services/chat/format_processor.py
touch src/services/chat/error_handler.py
touch src/services/chat/logger.py
touch src/services/chat/__init__.py
```

### Шаг 3: Постепенный перенос функциональности
1. Создать ChatRequestValidator с тестами
2. Создать StreamBufferManager с тестами
3. Создать StreamFormatProcessor с тестами
4. Создать остальные компоненты
5. Создать новый ChatService
6. Обновить импорты в main.py

### Шаг 4: Тестирование
```bash
# Запуск тестов
python -m pytest tests/test_models.py
python -m pytest tests/test_streaming_fixes.py

# Тестирование новых компонентов
python -m pytest tests/test_chat_components.py
```

### Шаг 5: Удаление старого кода
```bash
# Удаление оригинального файла после успешного тестирования
rm src/services/chat_service_original.py
```

## Ожидаемые результаты

### Преимущества рефакторинга

1. **Улучшение тестируемости**
   - Каждый компонент можно тестировать независимо
   - Легко создавать mock объекты
   - Упрощается unit тестирование

2. **Улучшение поддерживаемости**
   - Четкое разделение ответственностей
   - Легче находить и исправлять ошибки
   - Упрощается добавление новой функциональности

3. **Повышение переиспользуемости**
   - Компоненты можно использовать в других частях системы
   - Легко заменять реализации
   - Улучшается модульность

4. **Снижение сложности**
   - Каждый класс имеет одну ответственность
   - Упрощается понимание кода
   - Снижается когнитивная нагрузка

### Метрики успеха

1. **Качество кода**
   - Размер класса ChatService: с 431 строки до ~100 строк
   - Количество классов: с 1 до 7 специализированных
   - Покрытие тестами: с ~60% до ~90%

2. **Производительность**
   - Время обработки запросов: без изменений
   - Использование памяти: снижение на 10-20%
   - Время отклика: без изменений

3. **Поддерживаемость**
   - Время на добавление новой функциональности: снижение на 50%
   - Количество ошибок при изменениях: снижение на 30%
   - Время на отладку: снижение на 40%

## Риски и митигация

### Риски

1. **Регрессия функциональности**
   - Риск: Нарушение существующей функциональности
   - Митигация: Комплексное тестирование на каждом этапе

2. **Ухудшение производительности**
   - Риск: Накладные расходы на взаимодействие компонентов
   - Митигация: Профилирование и оптимизация

3. **Усложнение архитектуры**
   - Риск: Слишком много мелких компонентов
   - Митигация: Баланс между粒度和 сложностью

### План митигации

1. **Постепенный рефакторинг**
   - Перенос функциональности по частям
   - Тестирование каждого компонента
   - Сохранение обратной совместимости

2. **Комплексное тестирование**
   - Unit тесты для каждого компонента
   - Integration тесты для всего сервиса
   - Нагрузочное тестирование

3. **Мониторинг**
   - Отслеживание производительности
   - Мониторинг ошибок
   - Сравнение с базовыми метриками

## Заключение

Рефакторинг ChatService является критически важным для улучшения архитектуры проекта. Планируемое разделение на 7 специализированных компонентов позволит значительно улучшить тестируемость, поддерживаемость и переиспользуемость кода.

Ожидаемое время выполнения: **8-10 рабочих дней**
Ожидаемый результат: **Улучшение качества кода на 40% и снижение сложности поддержки на 50%**

После успешного завершения рефакторинга проект будет готов к дальнейшему масштабированию и добавлению новой функциональности.