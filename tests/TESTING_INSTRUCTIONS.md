# Инструкция по тестированию модуля chat_service

**Дата:** 2025-10-04  
**Версия:** 1.0  
**Автор:** Kilo Code

---

## 📋 Содержание

1. [Обзор тестовой структуры](#обзор-тестовой-структуры)
2. [Запуск тестов](#запуск-тестов)
3. [Типы тестов](#типы-тестов)
4. [Unit тесты](#unit-тесты)
5. [Интеграционные тесты](#интеграционные-тесты)
6. [Тесты производительности](#тесты-производительности)
7. [Тесты гибридного формата](#тесты-гибридного-формата)
8. [E2E тесты](#e2e-тесты)
9. [Рекомендации по разработке](#рекомендации-по-разработке)
10. [Отладка тестов](#отладка-тестов)

---

## 📁 Обзор тестовой структуры

```
tests/
├── TESTING_INSTRUCTIONS.md          # Эта инструкция
├── unit/                           # Unit тесты
│   ├── test_format_detector.py     # Тесты детектора формата
│   └── test_parsed_event.py        # Тесты парсинга событий
├── integration/                    # Интеграционные тесты
│   └── test_refactored_streaming.py # Тесты рефакторинга стриминга
├── performance/                     # Тесты производительности
│   └── test_parsing_optimization.py # Тесты оптимизации парсинга
├── test_hybrid_stream_format.py     # Тесты гибридного формата
├── test_smart_buffering_integration.py # Тесты умной буферизации
├── test_large_responses_detailed.py # Тесты больших ответов
├── test_streaming_fixes.py         # Тесты исправлений стриминга
├── test_ttft_external.py          # Тесты TTFT
├── test_hybrid_stream_format.py    # Тесты гибридного формата
├── integration/                    # Интеграционные тесты
│   └── test_refactored_streaming.py
├── e2e/                           # E2E тесты
│   └── test_streaming_refactored_e2e.py
└── TESTS.md                       # Общая документация по тестам
```

---

## 🚀 Запуск тестов

### Запуск всех тестов
```bash
python -m pytest tests/ -v
```

### Запуск конкретных типов тестов

#### Unit тесты
```bash
python -m pytest tests/unit/ -v
```

#### Интеграционные тесты
```bash
python -m pytest tests/integration/ -v
```

#### Тесты производительности
```bash
python -m pytest tests/performance/ -v
```

#### Тесты гибридного формата
```bash
python -m pytest tests/test_hybrid_stream_format.py -v
```

#### E2E тесты
```bash
python -m pytest tests/e2e/ -v
```

### Запуск с покрытием кода
```bash
python -m pytest tests/ --cov=src/services/chat --cov-report=html
```

### Запуск с подробным выводом
```bash
python -m pytest tests/ -v --tb=long
```

---

## 🧪 Типы тестов

### 1. Unit тесты
- **Цель:** Тестирование отдельных компонентов в изоляции
- **Файлы:** `tests/unit/`
- **Компоненты:**
  - `StreamFormatDetector` - детектирование формата стрима
  - `ParsedStreamEvent` - парсинг событий
- **Особенности:** Быстрые, изолированные, без зависимостей

### 2. Интеграционные тесты
- **Цель:** Тестирование взаимодействия компонентов
- **Файлы:** `tests/integration/`
- **Компоненты:**
  - `SmartStreamBufferManager` - буферизация стрима
  - `StreamingHandler` - обработка стрима
- **Особенности:** Проверяют совместную работу компонентов

### 3. Тесты производительности
- **Цель:** Оценка производительности и оптимизации
- **Файлы:** `tests/performance/`
- **Компоненты:**
  - Оптимизация парсинга JSON
  - Эффективность использования памяти
- **Особенности:** Измеряют время выполнения и потребление ресурсов

### 4. Тесты гибридного формата
- **Цель:** Тестирование работы с разными форматами стрима
- **Файлы:** `tests/test_hybrid_stream_format.py`
- **Компоненты:**
  - SSE (Server-Sent Events)
  - NDJSON (Newline Delimited JSON)
- **Особенности:** Проверяют автоопределение и конвертацию форматов

### 5. E2E тесты
- **Цель:** Тестирование полного цикла работы
- **Файлы:** `tests/e2e/`
- **Компоненты:** Полный поток обработки запросов
- **Особенности:** Медленные, но проверяют всю систему

---

## 🔧 Unit тесты

### test_format_detector.py
**Цель:** Тестирование детектора формата стрима

```python
# Пример теста
def test_sse_detection_with_data():
    """Тест детектирования SSE с data:"""
    assert StreamFormatDetector.detect('data: {"test": "value"}') == 'sse'

def test_ndjson_detection():
    """Тест детектирования NDJSON"""
    assert StreamFormatDetector.detect('{"message": {"content": "test"}}') == 'ndjson'
```

**Что тестирует:**
- Детектирование SSE формата
- Детектирование NDJSON формата
- Fallback на SSE при невалидном JSON
- Граничные случаи

### test_parsed_event.py
**Цель:** Тестирование парсинга событий стрима

```python
# Пример теста
def test_sse_content_extraction():
    """Тест извлечения контента из SSE"""
    event = ParsedStreamEvent(
        raw='data: {"choices": [{"delta": {"content": "hello"}}]}',
        format='sse',
        data={"choices": [{"delta": {"content": "hello"}}]}
    )
    assert event.content == "hello"
```

**Что тестирует:**
- Извлечение контента из SSE
- Извлечение контента из NDJSON
- Извлечение usage данных
- Проверку завершающих событий

---

## 🔗 Интеграционные тесты

### test_refactored_streaming.py
**Цель:** Тестирование рефакторинга стриминга

```python
# Пример теста
@pytest.mark.asyncio
async def test_sse_stream_no_double_parse():
    """Тест SSE стрима без двойного парсинга"""
    # Создаем мок ответа
    mock_response = Mock()
    mock_response.body_iterator = AsyncMock()
    
    # SSE чанки
    sse_chunks = [
        b'data: {"id": "1"}\n\n',
        b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n'
    ]
    mock_response.body_iterator.__aiter__.return_value = iter(sse_chunks)
    
    # Проверяем обработку
    result_chunks = []
    async for chunk in handler.handle_stream(mock_response, "openai", "gpt-4", "test-123", "user", "sse"):
        result_chunks.append(chunk)
    
    assert len(result_chunks) > 0
```

**Что тестирует:**
- Обработку SSE стрима
- Обработку NDJSON стрима
- Буферизацию оставшихся данных
- Восстановление UTF-8 последовательностей

---

## ⚡ Тесты производительности

### test_parsing_optimization.py
**Цель:** Оценка оптимизации парсинга

```python
# Пример теста
def test_no_double_parsing_performance():
    """Тест производительности без двойного парсинга"""
    # Создаем тестовые данные
    test_data = '{"message": {"content": "test"}}' * 1000
    
    # Замеряем время
    start_time = time.time()
    for _ in range(100):
        event = ParsedStreamEvent(
            raw=test_data,
            format='ndjson',
            data=json.loads(test_data)
        )
        _ = event.content
    end_time = time.time()
    
    # Проверяем, что время в пределах нормы
    assert end_time - start_time < 0.1  # Меньше 100ms
```

**Что тестирует:**
- Производительность парсинга
- Эффективность использования памяти
- Скорость обработки чанков
- Пиковое потребление памяти

---

## 🔄 Тесты гибридного формата

### test_hybrid_stream_format.py
**Цель:** Тестирование работы с разными форматами

```python
# Пример теста
@pytest.mark.asyncio
async def test_auto_detection_sse():
    """Тест автоопределения SSE формата"""
    # Мок ответа без предопределенного формата
    mock_response = Mock()
    mock_response.body_iterator = AsyncMock()
    
    # SSE чанки
    sse_chunks = [
        b'data: {"id": "1"}\n\n',
        b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n'
    ]
    mock_response.body_iterator.__aiter__.return_value = iter(sse_chunks)
    
    # Вызываем без предопределенного формата
    result_chunks = []
    async for chunk in handler.handle_stream(
        mock_response, 
        "unknown_provider", 
        "unknown-model", 
        "test-789", 
        "test-user",
        None  # Автоопределение
    ):
        result_chunks.append(chunk)
    
    assert len(result_chunks) > 0
```

**Что тестирует:**
- Автоопределение формата
- Конфигурируемый формат
- Конвертацию форматов
- Граничные случаи

---

## 🌐 E2E тесты

### test_streaming_refactored_e2e.py
**Цель:** Тестирование полного цикла работы

```python
# Пример теста
@pytest.mark.asyncio
async def test_full_chat_completion_flow():
    """Тест полного цикла чат-комплит"""
    # Создаем тестовый запрос
    request_data = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "Hello"}]
    }
    
    # Создаем мок провайдера
    with patch('src.services.chat_service.get_provider_instance') as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.chat_completions.return_value = mock_response
        mock_get_provider.return_value = mock_provider
        
        # Выполняем запрос
        response = await chat_service.chat_completions(mock_request, auth_data)
        
        # Проверяем результат
        assert response.status_code == 200
```

**Что тестирует:**
- Полный цикл обработки запроса
- Взаимодействие с провайдерами
- Обработку ошибок
- Логирование

---

## 🛠️ Рекомендации по разработке

### 1. При добавлении новых тестов
```python
# Структура теста
class TestComponent:
    def setup_method(self):
        """Инициализация перед каждым тестом"""
        self.component = Component()
    
    def test_feature(self):
        """Тестирование конкретной функции"""
        # Arrange - подготовка данных
        # Act - выполнение действия
        # Assert - проверка результата
```

### 2. Тестирование асинхронных функций
```python
@pytest.mark.asyncio
async def test_async_feature():
    """Тест асинхронной функции"""
    result = await async_function()
    assert result == expected_value
```

### 3. Мокирование зависимостей
```python
from unittest.mock import Mock, AsyncMock, patch

# Мокирование синхронной функции
with patch('module.function') as mock_function:
    mock_function.return_value = mock_value
    result = module.using_function()
    assert result == expected_value

# Мокирование асинхронной функции
with patch('module.async_function') as mock_async_function:
    mock_async_function.return_value = AsyncMock(return_value=mock_value)
    result = await module.using_async_function()
    assert result == expected_value
```

### 4. Тестирование ошибок
```python
def test_error_handling():
    """Тест обработки ошибок"""
    with pytest.raises(ExpectedException) as exc_info:
        function_that_raises_error()
    
    assert exc_info.value.args[0] == "Expected error message"
```

### 5. Параметризованные тесты
```python
@pytest.mark.parametrize("input,expected", [
    ("input1", "output1"),
    ("input2", "output2"),
    ("input3", "output3"),
])
def test_parametrized_function(input, expected):
    """Тест с параметризацией"""
    result = function(input)
    assert result == expected
```

---

## 🔍 Отладка тестов

### 1. Запуск с отладкой
```bash
# Запуск с выводом всех деталей
python -m pytest tests/ -v --tb=long

# Запуск конкретного теста с отладкой
python -m pytest tests/unit/test_format_detector.py::TestStreamFormatDetector::test_sse_detection_with_data -v --tb=long

# Запуск с паузой для отладки
python -m pytest tests/ --pdb
```

### 2. Логирование в тестах
```python
import logging

# Включение логирования
logging.basicConfig(level=logging.DEBUG)

# Логирование в тестах
logger = logging.getLogger(__name__)
logger.debug("Debug message in test")
```

### 3. Профилирование тестов
```bash
# Профилирование времени выполнения
python -m pytest tests/ --durations=10

# Профилирование памяти
python -m pytest tests/ --profile-svg
```

### 4. Тестирование с覆盖率
```bash
# Генерация отчета о покрытии
python -m pytest tests/ --cov=src/services/chat --cov-report=html --cov-report=term

# Проверка минимального покрытия
python -m pytest tests/ --cov=src/services/chat --cov-fail-under=80
```

---

## 📊 Ожидаемые результаты тестов

### Unit тесты
- **Количество:** 15 тестов
- **Ожидаемый результат:** 15/15 passed
- **Время выполнения:** < 1 секунда

### Интеграционные тесты
- **Количество:** 4 теста
- **Ожидаемый результат:** 4/4 passed
- **Время выполнения:** < 5 секунд

### Тесты производительности
- **Количество:** 2 теста
- **Ожидаемый результат:** 2/2 passed
- **Время выполнения:** < 10 секунд

### Тесты гибридного формата
- **Количество:** 10 тестов
- **Ожидаемый результат:** 10/10 passed
- **Время выполнения:** < 10 секунд

### E2E тесты
- **Количество:** 1 тест
- **Ожидаемый результат:** 1/1 passed
- **Время выполнения:** < 30 секунд

---

## 🚨 Важные замечания

1. **Не изменяйте сигнатуры тестов** без согласования
2. **Добавляйте тесты** для нового функционала
3. **Обновляйте документацию** при изменении тестов
4. **Проверяйте покрытие** после добавления тестов
5. **Избегайте мокирования всего** - тестируйте реальные компоненты

---

## 📞 Контакты

При возникновении вопросов по тестированию:
- **Email:** kilo@example.com
- **GitHub Issues:** Создайте issue в репозитории
- **Slack:** Канал #testing

---

**Дата последнего обновления:** 2025-10-04  
**Версия:** 1.0