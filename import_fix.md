# Исправление импорта в OpenAI провайдере

## Проблема

Ошибка в логе:
```
ImportError: attempted relative import beyond top-level package
```

## Решение

В файле `src/providers/openai.py` нужно заменить строку:

```python
from ...core.config_manager import ConfigManager
```

на:

```python
from src.core.config_manager import ConfigManager
```

Это исправление заменит относительный импорт на абсолютный, что решит проблему с запуском в контейнере.