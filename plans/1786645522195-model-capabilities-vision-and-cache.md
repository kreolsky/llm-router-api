# План: возможности моделей (vision) + автокэш параметров

**Статус:** черновик, к исполнению
**Цель:** декларировать клиентам полный набор параметров модели (контекст, лимит вывода, модальности/vision, поддерживаемые параметры, цены) и перестать ходить в upstream на каждый `GET /v1/models/{id}`.

## Контекст / текущее состояние

* Ручной каталог `config/model_info.yaml` (`model_info:` секция), подмешивается в ответы в `ModelService._build_model_response` — в списке (`model_service.py:52-53`) и в детали (`model_service.py:116-123`).
* Live-обогащение `ModelService._get_model_details_from_provider` (`model_service.py:56-94`) на каждый запрос делает `provider.get_model()` → `list_models()` → полный сетевой `GET /models` у апстрима. Кэша нет. В `/v1/models` (список) live-данных нет вовсе.
* Приоритет слияния сейчас: `{**provider_details, **model_info}` — ручной YAML выигрывает. Сохраняем это правило.
* Проброс vision-контента уже работает: `chat_completions` форвардит тело как есть, `content: [{type: image_url}]` не модифицируется. Отсутствует **декларация** возможностей, а не проброс.

### Что реально отдают апстримы

| Провайдер | `/models` содержит |
|---|---|
| `openrouter` | всё: `context_length`, `architecture.input_modalities` (`image` → vision), `top_provider.max_completion_tokens`, `supported_parameters`, `pricing` |
| `deepseek` | только `id`/`object`/`owned_by` — пусто |
| `kimi` (moonshot) | практически только `id` |
| `orange` (llama-server) | `id`, в свежих сборках `meta.n_ctx_train`; реальный `n_ctx` и наличие mmproj (vision) — только через `GET /props` |

Вывод: автокэш полностью наполняет только openrouter (+частично orange). Ручной YAML остаётся источником истины для остальных. Поэтому делаем оба слоя.

---

## Формат ответа (зафиксировано)

Ориентир — OpenRouter, но наш текущий ответ OpenAI-shaped (`object`, `owned_by`, `permission`, `root`, `parent` — `model_service.py:15-37`), а у OpenRouter этих полей нет. Ломать их нельзя. Итоговый формат = **надмножество: база OpenAI + поля OpenRouter поверх**.

### `GET /v1/models` — элемент `data[]`

```json
{
  "id": "gemini/mini",
  "object": "model",
  "created": 1786645522,
  "owned_by": "nnp-llm-router",
  "root": "gemini/mini",
  "parent": null,
  "permission": [ ... ],

  "name": "Google: Gemini 2.0 Flash",
  "description": "Google Gemini 2.0 Flash — fast, multimodal, tool calling",
  "context_length": 1048576,
  "max_completion_tokens": 8192,
  "architecture": {
    "modality": "text+image->text",
    "input_modalities": ["text", "image"],
    "output_modalities": ["text"],
    "tokenizer": "Gemini",
    "instruct_type": null
  },
  "top_provider": {
    "context_length": 1048576,
    "max_completion_tokens": 8192,
    "is_moderated": false
  },
  "pricing": {
    "prompt": "0.0000001",
    "completion": "0.0000004",
    "request": "0",
    "image": "0.0000258",
    "web_search": "0",
    "internal_reasoning": "0",
    "input_cache_read": "0.000000025"
  },
  "supported_parameters": ["tools", "tool_choice", "max_tokens", "temperature", "top_p", "stream"],
  "per_request_limits": null,
  "supports_vision": true,
  "reasoning": { "supported": false }
}
```

### `GET /v1/models/{id}`

Тот же объект + наши служебные поля (уже отдаются сегодня): `provider`, `provider_model_name`, `params`, `options`, плюс новые `capabilities_source`, `capabilities_fetched_at`.
Оболочку **не меняем**: OpenRouter отдаёт деталь как `{"data": {...}}`, мы отдаём объект плоско, как сейчас. Клиенты уже читают плоско.

### Принятые решения

1. **`max_completion_tokens` дублируется.** Канонично — в `top_provider.max_completion_tokens` (как у OpenRouter), плюс плоско на верхнем уровне для обратной совместимости с текущим `model_info.yaml`.
2. **Цены — строки, за токен.** В YAML пишем числами (читаемо), при сериализации форматируем в строку без экспоненциальной записи (`float` дал бы `4.35e-07`, на чём спотыкаются парсеры клиентов). Отдаём полный набор ключей OpenRouter, отсутствующие → `"0"`.
3. **`reasoning` — только наш блок.** `"reasoning"` в `supported_parameters` НЕ подмешиваем: `default_enabled` (включён ли thinking через `options` в `models.yaml`) в схеме OpenRouter невыразим, а два источника правды про одно и то же разъедутся. Само поле `supported_parameters` остаётся — оно несёт `tools`/`temperature`/и т.д.
4. **`supports_vision`** — единственное поле вне OR-схемы, добавляется сознательно для харнесов, не читающих `input_modalities`. Вычисляется, не хранится.
5. **`architecture.modality`** (строка `text+image->text`) генерится из модальностей, в YAML не хранится.

---

## Часть A — единая схема `model_info` + vision (ручной слой)

### A1. Зафиксировать нормализованную схему

Поля `model_info.yaml` (все опциональные). Хранимая форма минимальна — производные поля (`modality`, `supports_vision`, `top_provider`, дублирование `max_completion_tokens`, строковые цены) собираются на сериализации:

```yaml
model_info:
  <model_id>:
    name: str                               # опц., человекочитаемое имя
    description: str
    context_length: int
    max_completion_tokens: int
    is_moderated: bool                      # опц., → top_provider.is_moderated
    architecture:
      input_modalities: [text, image]       # наличие "image" == vision
      output_modalities: [text]
      tokenizer: str                        # опц.
      instruct_type: str                    # опц.
    supported_parameters: [tools, tool_choice, max_tokens, temperature, ...]
    reasoning:
      supported: bool
      default_enabled: bool
    pricing:                                # числа; в JSON уходят строками
      prompt: float
      completion: float
      input_cache_read: float
      image: float                          # опц.
```

* **Vision выражается через `architecture.input_modalities`, а не булевым флагом в YAML.**
* Задокументировать схему в шапке `config/model_info.yaml` и в `README.md`.

### A2. Починить протухшие записи

* `local/orange` → отсутствующий ключ; в `models.yaml` теперь `local/chat` и `local/reasoner` (разные `chat_template_kwargs`, но одна и та же backend-модель). Развести на две записи.
* `kimi`: описание «Kimi K2.6», а `provider_model_name: kimi-k2.7-code`. Обновить описание и `max_completion_tokens`.
* Добавить `architecture.input_modalities` всем существующим записям (`gemini/mini` — `[text, image]`; deepseek/kimi/local — уточнить по факту, см. C).
* `embeddings/dummy` и `stt/dummy` — `is_hidden`, в каталоге не нужны.

### A3. Отдавать возможности в обоих эндпоинтах

* Один сериализатор `render_capabilities(model_info: dict) -> dict` — единственное место, где хранимая форма превращается в ответ по спецификации выше. Отвечает за все производные поля: `architecture.modality`, `supports_vision`, `top_provider.{context_length,max_completion_tokens,is_moderated}`, плоское дублирование `max_completion_tokens`, приведение `pricing` к строкам без экспоненты, добивку недостающих ключей `pricing` нулями, `per_request_limits: null`.
* `list_models` (строка 53) и `retrieve_model` (строка 123) оба идут через него — список и деталь не разъезжаются по определению.
* Форматирование цены: `f"{value:.12f}".rstrip("0")` с защитой от пустой дробной части, либо `decimal.Decimal(str(value))` → `format(d, 'f')`. Выбрать на реализации, покрыть юнит-тестом на `4.35e-07`.

### A4. Валидация

* Мягкая проверка при загрузке `model_info.yaml`: неизвестные ключи и `model_info`-записи без соответствующей модели в `models.yaml` → `logger.warning` (не фатально — файл `required=False`, `config_manager.py:55`).

---

## Часть B — автокэш параметров из апстримов

### B1. Модуль `src/core/model_capabilities.py`

* `normalize_provider_model(provider_type, raw: dict) -> dict` — приводит сырой ответ апстрима к **хранимой** схеме A1 (не к форме ответа): разворачивает `top_provider.max_completion_tokens` в плоское поле, парсит строковые цены OpenRouter обратно в числа, отбрасывает производные (`modality`). Отдельные мапперы: openrouter-shape, llama-server-shape (`meta.n_ctx_train`, `/props`), generic OpenAI (почти пусто).
* Инвариант: кэш и `model_info.yaml` хранят одну и ту же форму — иначе deep-merge в B3 некорректен.
* `"reasoning"` из `supported_parameters` апстрима в наш блок `reasoning` **не транслируется** (решение 3): блок `reasoning` заполняется только вручную.
* `CapabilitiesCache` — хранит `{model_id: {"data": {...}, "fetched_at": ts, "source": provider_name}}`, персист в `data/model_cache.json` (атомарная запись через `.tmp` + `os.replace`, как в остальном коде).
* Кэш читается с диска на старте → данные доступны сразу, даже если апстрим лежит.

### B2. Фоновая задача обновления

* Отдельная задача рядом с `config_manager.start_reloader_task()`, запуск из `lifespan` (`main.py:57-60`).
* Интервал: `MODEL_CACHE_REFRESH_INTERVAL` (default `3600`), TTL записи `MODEL_CACHE_TTL` (default `86400`); выключатель `MODEL_CACHE_ENABLED` (default `true`). Все — через свойства `ConfigManager` (правило: никаких `os.getenv` вне ConfigManager).
* Первый прогон — **после** yield/в фоне, не блокируя старт: недоступный апстрим не должен мешать подняться (в отличие от `_validate_providers`, который fail-fast намеренно).
* Один `list_models()` на провайдера (не на модель), затем раздача по всем `model_id`, ссылающимся на этот провайдер. Ошибки провайдера — `logger.warning`, старое значение кэша сохраняется (stale-if-error).
* На reload конфига провайдерский кэш пересоздаётся (`rebuild_provider_cache`) — задача должна брать инстансы через тот же реестр, а не держать свои ссылки.

### B3. Приоритет источников

`model_info.yaml` (ручной override) > автокэш > пусто.
Реализовать в `ModelService`, заменив текущий `{**additional_model_details, **model_info}`; merge — по полям верхнего уровня, вложенные (`architecture`, `pricing`) мержить через `deep_merge` (`src/utils/deep_merge.py`), чтобы частичный ручной override не затирал остальное.

### B4. Убрать сетевой вызов из горячего пути

* `retrieve_model` перестаёт вызывать `_get_model_details_from_provider` — читает из кэша.
* `_get_model_details_from_provider` остаётся, но вызывается только фоновой задачей (и, опционально, при `?refresh=true` для отладки).
* В ответ добавить `capabilities_source`/`capabilities_fetched_at` (диагностика: откуда данные и насколько свежие).

---

## Часть C — оффлайн-скрипт зондирования (опционально, не в рантайме)

`scripts/probe_models.py` — для `deepseek`/`kimi`, где апстрим не отдаёт ничего:

* vision: одиночный запрос с 1×1 PNG в `image_url` → успех/ошибка;
* контекст/лимит вывода: запрос заведомо превышающей длины, парсинг сообщения об ошибке (без бинарного поиска — дорого и флаки).

Скрипт **пишет YAML-заготовку в stdout** для ручного вклеивания в `model_info.yaml`. Никогда не правит конфиг сам, никогда не запускается из приложения (платные запросы).

---

## Тесты

`tests/unit/test_model_capabilities.py` (новый):
* нормализация openrouter-ответа → хранимая схема (строковые цены → числа, `top_provider` → плоский `max_completion_tokens`);
* сериализация `render_capabilities`: `input_modalities` → `supports_vision` и `architecture.modality`; `max_completion_tokens` присутствует и плоско, и в `top_provider`; недостающие ключи `pricing` = `"0"`;
* формат цен: `4.35e-07` → `"0.000000435"`, без экспоненты (регрессионный тест на решение 2);
* `"reasoning"` в `supported_parameters` апстрима не попадает в наш блок `reasoning` (решение 3);
* нормализация llama-server-ответа (`meta.n_ctx_train`, отсутствие полей);
* generic OpenAI-ответ → пустой словарь, без исключений;
* приоритет `model_info` над кэшем, deep-merge вложенных `architecture`/`pricing`;
* stale-if-error: провайдер падает → прежнее значение кэша живёт;
* персист/чтение `data/model_cache.json`, битый JSON → игнор + warning.

`tests/unit/test_model_service.py` (правки):
* `retrieve_model` не делает сетевых вызовов (мок провайдера не должен быть тронут);
* `supports_vision` присутствует и в списке, и в детали.

`tests/api/test_models_endpoints.py` (правки):
* `/v1/models` отдаёт `context_length`/`max_completion_tokens`/`architecture`/`supports_vision` для сконфигурированных моделей;
* скрытые модели по-прежнему скрыты, access-control не задет.

Прогон: скилл `run-tests` (unit + API на порту 8777).

---

## Документация

* `CLAUDE.md` — новая секция «Model Capabilities»: два слоя (ручной YAML + автокэш), приоритет, где живёт кэш, новые env-переменные.
* `README.md` — схема `model_info.yaml` с примером vision-модели.
* `# ARCH:` — на приоритете источников и на «кэш обновляется фоном, горячий путь в сеть не ходит»; `# INVARIANT:` — «`model_info.yaml` всегда выигрывает у автокэша».

## Порядок работ

1. A1–A2 (схема + починка каталога) — самостоятельная ценность, деплоится сразу.
2. A3–A4 (`supports_vision`, хелпер, валидация) + тесты.
3. B1 (нормализаторы + кэш) + юнит-тесты — без подключения к приложению.
4. B2–B4 (фоновая задача, приоритет, вынос сети из горячего пути) + тесты.
5. Документация, прогон полного набора тестов, деплой (скилл `deploy-server`).
6. C — отдельно, по потребности.

## Риски / открытые вопросы

* **`config/` на сервере authoritative** и rsync'ом не перетирается — правки `model_info.yaml` нужно применять на сервере вручную. Учесть при деплое.
* `data/model_cache.json` — том должен переживать рестарт контейнера (проверить `docker-compose.yml`, там уже есть `data/` для `usage_db`).
* `local/chat` и `local/reasoner` указывают на одну backend-модель `dummy` у `orange` — автокэш даст обеим одинаковые значения; отличия (reasoning) остаются ручными.
* llama-server `/props` — нестандартный эндпоинт вне `openai`-абстракции. Либо отдельный маппер с фича-флагом на провайдере, либо ограничиться `meta.n_ctx_train`. Решить на шаге B1; при сомнении — ручной YAML.
