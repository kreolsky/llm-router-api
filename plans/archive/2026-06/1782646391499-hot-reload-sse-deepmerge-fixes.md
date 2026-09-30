# Архитектурные фиксы — hot-reload, SSE, deep_merge

Три изолированных исправления. Порядок не важен — файлы не пересекаются.

---

## Task 1 — Async протокол колбэков reload_config

**Проблема:** `reload_config` свапает `self.config` до вызова колбэков. Если `rebuild_provider_cache` падает — конфиг новый, кэш старый.

**Файлы:** `src/core/config_manager.py`, `src/api/main.py`

### config_manager.py

1. Изменить сигнатуру `add_reload_callback` — принимать `name: str` (новая сигнатура колбэка: `cb(new_config: dict)`). Обновить докстринг метода, явно описав новую сигнатуру колбэка и имя:
```python
def add_reload_callback(self, callback, name: str = ""):
    """Register an async callback invoked after a successful config load.

    callback signature: ``async def cb(new_config: dict) -> None``.
    On callback failure reload is aborted and self.config is NOT swapped
    (the previous config stays in place). Callbacks run sequentially.
    """
    self._on_reload_callbacks.append((name, callback))
```

2. Переписать `reload_config` на async. Колбэки вызываются последовательно с `await`, каждый получает `new_config`. При падении колбэка — лог с именем, return без свапа `self.config`. Старый конфиг остаётся. Обновить докстринг (теперь async, передаёт new_config, атомарность «старый конфиг при ошибке»):

```python
async def reload_config(self):
    """Reload config from disk and invoke registered async callbacks.

    Atomicity: self.config is swapped only AFTER every callback succeeds.
    If any callback raises, the previous config is retained (return, no swap).
    Each callback receives the freshly loaded new_config dict.
    """
    logger.info("Reloading configuration", ...)
    new_config = self._load_config(fail_on_error=False)
    if new_config.get('providers') and new_config.get('models') and new_config.get('user_keys'):
        for name, cb in self._on_reload_callbacks:
            try:
                await cb(new_config)
            except Exception as e:
                logger.error(
                    f"Config reload callback failed: {name or '(unnamed)'}",
                    extra={"config": {"operation": "reload_callback_error", "callback_name": name}},
                    exc_info=True,
                )
                return
        self.config = new_config
        logger.info("Configuration reloaded", ...)
    else:
        logger.warning("Partial config reload rejected, keeping previous config")
```

3. В `_reload_config_task` заменить `self.reload_config()` на `await self.reload_config()`.

### main.py

4. Убрать модульную переменную `_reload_tasks`.

5. Убрать функцию `_make_reload_callback`.

6. Заменить регистрацию колбэка:
```python
# Было:
config_manager.add_reload_callback(_make_reload_callback(config_manager))

# Станет:
async def _rebuild_on_reload(new_config: dict) -> None:
    await rebuild_provider_cache(new_config, config_manager)

config_manager.add_reload_callback(_rebuild_on_reload, name="rebuild_provider_cache")
```

7. Убедиться что импорт `rebuild_provider_cache` уже есть (да, `from ..providers import ... rebuild_provider_cache`).

### tests/unit/test_config_manager.py

`reload_config` стал корутиной, а колбэк — `async def cb(new_config: dict)`. Существующие тесты вызывают `cm.reload_config()` синхронно и используют `MagicMock` (не awaitable) — их **обязательно** переписать, иначе прогон упадёт.

8. В классах `TestReloadConfig` и `TestAddReloadCallback` заменить `MagicMock()` на `AsyncMock()` для колбэков, а вызовы `cm.reload_config()` — на `await cm.reload_config()`. Сами тест-методы пометить `@pytest.mark.asyncio` (проверить что в файле уже есть `pytestmark = pytest.mark.asyncio` или `asyncio_mode = "auto"` в `conftest`/`pyproject`; при отсутствии — добавить `@pytest.mark.asyncio` на каждый метод).

   - `TestReloadConfig.test_invokes_callbacks_on_change` (стр. ~192): `AsyncMock`, `await`, + `callback.assert_awaited_once_with(<new_config>)` (колбэк теперь получает new_config).
   - `TestReloadConfig.test_rejects_partial_config_keeps_previous` (стр. ~205): `AsyncMock`, `await`; behaviour не меняется (partial → callback не вызывается, конфиг прежний).
   - `TestAddReloadCallback.test_callback_called_on_reload` (стр. ~340): `AsyncMock`, `await`.
   - `TestAddReloadCallback.test_multiple_callbacks` (стр. ~352): оба `AsyncMock`, `await`.

9. Добавить новый тест на инвариант атомарности: колбэк падает → `self.config` НЕ свапнут, остаётся прежний:
```python
@pytest.mark.asyncio
async def test_callback_failure_keeps_previous_config(self):
    cm = _build_config_manager()
    original_config = cm.get_config().copy()
    failing_cb = AsyncMock(side_effect=RuntimeError("boom"))
    cm.add_reload_callback(failing_cb, name="failing")

    with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
         patch("src.core.config_manager.logger"):
        await cm.reload_config()

    failing_cb.assert_awaited_once()
    assert cm.get_config() == original_config  # old config retained
```

**Валидация:** `python -m pytest tests/unit/test_config_manager.py tests/unit/test_provider_registry.py tests/unit/test_startup_validation.py -v`

---

## Task 2 — SSE-комментарий: лишний `\r`

**Проблема:** `buffer.split("\n", 1)` оставляет `\r` в конце строки комментария при `\r\n` разделителе. Выходной SSE синтаксически валиден, но код хрупкий.

**Файл:** `src/services/chat_service/stream_processor.py`

**Изменение:** строка 156, после split добавить rstrip:
```python
# Было:
comment_line, buffer = buffer.split("\n", 1)

# Станет:
comment_line, buffer = buffer.split("\n", 1)
comment_line = comment_line.rstrip("\r")
```

**Валидация:** `python -m pytest tests/unit/test_stream_processor.py -v`

---

## Task 3 — deep_merge: конкатенация списков

**Проблема:** Списки в `options` (models.yaml) перезаписываются вместо расширения. Сейчас списков в options нет — проблема гипотетическая.

**Файл:** `src/utils/deep_merge.py`

**Изменение:** добавить `elif` ветку после существующей dict-обработки:
```python
# После:
if key in result and isinstance(result[key], dict) and isinstance(value, dict):
    result[key] = deep_merge(result[key], value)
# Добавить:
elif key in result and isinstance(result[key], list) and isinstance(value, list):
    result[key] = result[key] + value
# Существующий else остаётся:
else:
    result[key] = value
```

### tests/unit/test_utilities.py

Добавить тест, фиксирующий новую семантику (конкатенация без дедупликации):
```python
def test_deep_merge_concatenates_lists():
    """Lists are concatenated (left then right), no deduplication."""
    merged = deep_merge({"tags": [1, 2]}, {"tags": [3, 2]})
    assert merged == {"tags": [1, 2, 3, 2]}

def test_deep_merge_list_replaces_non_list():
    """A list overwrites a non-list value of the same key."""
    merged = deep_merge({"tags": "old"}, {"tags": [1]})
    assert merged == {"tags": [1]}
```

**Валидация:** `python -m pytest tests/unit/test_utilities.py -v`

---

## Риски

- **Task 1:** `reload_config` становится async. Единственный вызывающий — `_reload_config_task` (уже async). Сторонних вызовов нет.
- **Task 1:** Сигнатура колбэка сменилась с `cb()` на `async def cb(new_config: dict)`. В кодовой базе других колбэков нет, но это breaking change API `add_reload_callback` — отражён в обновлённом докстринге.
- **Task 1:** Колбэк теперь ждётся напрямую, блокируя polling-луп на время перестройки кэша (~1-2с). При интервале reload 5с допустимо. Fallback `asyncio.run(...)` убран — в проде колбэк всегда вызывается из running loop (`_reload_config_task`).
- **Task 2:** `rstrip("\r")` идемпотентен — для чистого `\n` ничего не делает.
- **Task 3:** Конкатенация без дедупликации — семантически корректно для опций моделей. Поведение зафиксировано тестом `test_deep_merge_concatenates_lists`.

## Общая валидация

```bash
python -m pytest tests/unit/ -v
```
