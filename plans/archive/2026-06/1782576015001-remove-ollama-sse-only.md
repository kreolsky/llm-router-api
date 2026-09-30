# Plan: Remove Ollama — SSE as the only stream format

## Goal

Полностью вырезать провайдер Ollama и убрать мёртвую абстракцию `stream_format`.
После выполнения: единственный формат стрима — SSE (`text/event-stream`), единственный
тип провайдера — `openai`. Конфиг и код перестают противоречить друг другу.

## Context / why

- `stream_format` прописан у всех провайдеров в `config/providers.yaml`, но **ни разу не
  читается** кодом (`grep stream_format src/` → 0 совпадений). Это декоративное поле.
- `StreamProcessor` умеет парсить только SSE; `chat_service` всегда отдаёт
  `media_type="text/event-stream"`. NDJSON нигде не поддерживается реально.
- Ollama нативно отдаёт NDJSON, поэтому через текущий путь он был бы сломан под стримом.
- `README.md` документирует `stream_format: sse | ndjson` как рабочую фичу — это вводит в
  заблуждение.
- Ollama уходит в legacy и в проде не стримит → безопасно удалить без миграции данных.

## Scope decisions

- **Провайдер-абстракция сохраняется.** `get_provider_instance` остаётся с registry/кэшем
  по `(type, base_url)` и веткой `else → PROVIDER_NOT_FOUND`. Это точка расширения без
  лишнего кода.
- **`models.yaml`** — не трогается (моделей на ollama-провайдере там нет).
- **`.env`** — НЕ трогается (gitignored, server-authoritative). `OLLAMA_CONNECT_TIMEOUT`
  становится мёртвой строкой; пользователь чистит вручную по желанию.
- **`RULES.md`** — не трогается (упоминания generic: «providers/», «config entries» —
  остаются валидными).
- **`plans/jolly-soaring-badger.md`** — исторический архив, не трогается.
- NDJSON-хелперы в `tests/test_utils.py` удаляются (dead code в рамках Path A).

## Tasks (ordered)

### 1. `src/providers/ollama.py`
- **Удалить файл целиком.**

### 2. `src/providers/__init__.py`
- Убрать `from .ollama import OllamaProvider` (стр. 7).
- Убрать ветку `elif provider_type == "ollama":` и её тело (стр. 25-26).
- Оставить ветку `if provider_type == "openai":` и финальный `else` (raise
  `PROVIDER_NOT_FOUND`).
- Обновить module docstring, если он упоминает ollama (стр. 1 сейчас generic — проверить).

### 3. `src/core/config_manager.py`
- Удалить свойство `ollama_connect_timeout` (стр. 115-116) и его env-чтение
  `os.getenv("OLLAMA_CONNECT_TIMEOUT", ...)`.

### 4. `config/providers.yaml`
- Удалить блок `ollama:` целиком (стр. 35-38): `type`, `base_url`, `stream_format`.
- Удалить строку `stream_format: sse` у всех 6 openai-провайдеров
  (deepseek, kimi, openrouter, orange, embedding, transcriber) — стр. 6, 11, 16, 24, 29, 34.

### 5. `tests/test_utils.py`
- Удалить метод `parse_ndjson_stream` (стр. 59-67).
- В `collect_stream_content`: убрать параметр `stream_format: str = "sse"` (стр. 72) и
  ветку выбора парсера (стр. 80-83), захардкодить вызов `parse_sse_stream`.

### 6. Orphan pyc artifacts
- Удалить `tests/__pycache__/test_hybrid_stream_format.cpython-312-pytest-8.4.2.pyc`
  (исходника `.py` нет — это рудимент).
- Заодно очистить осиротевшие `ollama.*.pyc` в `src/providers/__pycache__/` (появятся после
  удаления исходника; безопасно — перегенерируются).

### 7. `README.md`
- Стр. 3: убрать «Ollama» из перечисления бэкендов.
- Стр. 34: убрать упоминание «Ollama options mapping».
- Стр. 48: комментарий `# openai | ollama` → `# openai`.
- Стр. 51: удалить `stream_format: sse # sse | ndjson`.
- Стр. 54-59: удалить пример блока `ollama:` и фразу про «ollama (maps parameters...)».
- Стр. 121: удалить строку `│   └── ollama.py # ...` из дерева структуры.

### 8. `CLAUDE.md`
- Стр. 3: убрать «Ollama» из «Routes requests to OpenAI, DeepSeek, OpenRouter, Ollama, ...».
- Стр. 21: «Two provider types (`openai`, `ollama`)» → «Single provider type (`openai`)».

## Risks & mitigations

- **Забытая ссылка на Ollama где-то ещё.** Mitigation: финальный `grep -rni
  "ollama\|stream_format\|ndjson" src/ config/ tests/ README.md CLAUDE.md` должен быть пуст
  (кроме исторического `plans/jolly-soaring-badger.md`).
- **Регрессия провайдер-фабрики.** Mitigation: прогон `tests/unit/test_base_provider.py` и
  `tests/unit/test_config_manager.py` (если последний проверяет свойство ollama-таймаута —
  удалить/править соответствующий кейс).
- **`_get_timeout("ollama_connect_timeout", ...)`** был единственным потребителем
  свойства — после удаления файла `ollama.py` ссылок не остаётся; перепроверить grep-ом.

## Validation

1. `ruff check .` и typecheck (если настроен в проекте — проверить наличие команды).
2. Полный прогон `pytest` (unit + api) — все зелёные.
3. `grep -rni "ollama" src/ config/ tests/ --include="*.py" --include="*.yaml"` → пусто.
4. `grep -rni "stream_format\|ndjson" src/ config/ tests/ --include="*.py" --include="*.yaml"`
   → пусто.
5. Старт сервиса (`docker compose up` или локально) + smoke: non-stream и stream запрос к
   любому openai-провайдеру отдают корректно (`text/event-stream` для стрима).

## Out of scope

- Редактирование `.env` (gitignored).
- Изменение `models.yaml`.
- Перепроектирование провайдер-абстракции.
- Любые правки, не перечисленные в Tasks.

## Open questions

Нет. Все решения зафиксированы в разделе Scope decisions.
