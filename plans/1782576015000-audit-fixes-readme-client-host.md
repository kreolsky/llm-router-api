# Plan: Audit Fixes — README sync, client.host safety, medium findings

## Context

Из аудита всплыли расхождения между документацией и кодом (anthropic-провайдер удалён в `3af8bbd`, но всё ещё описан в README), потенциальный AttributeError на `request.client.host`, и пять «средних» проблем — небольшие баги/защитные дыры, каждая по отдельности нестрашна, но накапливаются. Цель: одним PR закрыть документационный долг, защитные мелочи и корректность hot-reload-зависимых путей. Тесты не должны деградировать.

## Scope

6 точечных правок, все локализованы. Никакой архитектурной перестройки. Поведение по умолчанию не меняется. Пункт «Ollama enrichment в `model_service`» из плана исключён по решению пользователя.

---

## 1. README sync — удалить упоминания Anthropic

**Файл:** [README.md](README.md)

Изменения:
- Строка 121: убрать `anthropic.py # Translates OpenAI format → Anthropic Messages API` из дерева структуры.
- Строка 49: в комментарии заменить `openai | ollama | anthropic` → `openai | ollama`.
- Строка 59: переписать предложение, убрав упоминание `anthropic` provider class.
- Строка 34 (How It Works): убрать `Anthropic Messages API` из перечисления форматов.

Проверка: `grep -in anthropic README.md` должен возвращать пусто.

Дополнительно: в [README.md:150-151](README.md#L150-L151) убрать жёсткие числа «158 unit / 114 integration» — заменить на «полный набор unit-тестов» / «integration-тесты». То же в [RULES.md:98-99](RULES.md#L98-L99).

---

## 2. `request.client.host` — None-safety

**Файлы:** [src/api/main.py](src/api/main.py)

Точки риска:
- [src/api/main.py:129](src/api/main.py#L129) — endpoint `/v1/audio/transcriptions`
- [src/api/main.py:193](src/api/main.py#L193) — endpoint `/tools/generate_key`

Подход: ввести локальный helper в этом же модуле (на 3 строки, без новых файлов):
```python
def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"
```
Заменить оба `request.client.host` на `_client_host(request)`. Проверить `grep -n "client.host" src/` — других мест нет (middleware использует scope напрямую и не падает).

---

## 3. Retry decorator — защита `last_exception is None`

**Файл:** [src/providers/base.py:46-75](src/providers/base.py#L46-L75)

Проблема: при `PROVIDER_MAX_RETRIES=0` цикл выполнится один раз; non-429 пробросится через `raise e` (line 74), но если кто-то изменит структуру и `last_exception` останется `None`, `raise None` даст `TypeError`.

Фикс: на строке 75 заменить `raise last_exception` на:
```python
if last_exception:
    raise last_exception
raise RuntimeError("retry_on_rate_limit: exhausted without exception")
```
Это защита от регрессий, не меняет happy path.

---

## 4. `BaseProvider` — не мутировать `config["headers"]`

**Файл:** [src/providers/base.py:96](src/providers/base.py#L96)

Заменить:
```python
self.headers = config.get("headers", {})
```
на:
```python
self.headers = dict(config.get("headers") or {})
```

После этого `setdefault("Content-Type", ...)` и инжекция `Authorization` в [base.py:101](src/providers/base.py#L101) и [base.py:114](src/providers/base.py#L114) работают на копии, а не на ссылке из YAML-конфига. Защищает от утечки заголовков обратно в `model_service._get_provider_api_details`, который читает `provider_config["headers"]` напрямую ([model_service.py:40-41](src/services/model_service.py#L40-L41)).

---

## 5. `model_service` — Ollama enrichment

**Файл:** [src/services/model_service.py:70](src/services/model_service.py#L70)

Текущая строка:
```python
if not base_url or not api_key:
    return {}
```
У Ollama нет `api_key_env`, поэтому enrichment навсегда отключён.

Фикс: убрать `or not api_key`:
```python
if not base_url:
    return {}
```

`_fetch_provider_models` уже не отправляет `Authorization`, если ключа нет (см. [model_service.py:38-39](src/services/model_service.py#L38-L39) — header добавляется только если `provider_api_key`). То есть путь для Ollama безопасен. Если Ollama-эндпоинт `/models` ответит ошибкой — обогащение всё равно non-fatal (внешний `try/except` это уже ловит, [model_service.py:93-111](src/services/model_service.py#L93-L111)).

Замечание: Ollama base_url в конфиге `http://10.10.1.20:11434/api`, но OpenAI-совместимый endpoint у Ollama `/v1/models`, не `/api/models`. Возможно нужно отдельное условие на `provider_type == "ollama"` — **пометить как открытый вопрос** (см. ниже). Безопаснее всего: оставить ранний return на 404 и логировать как warning.

---

## 6. Docker-compose healthcheck

**Файл:** [docker-compose.yml](docker-compose.yml)

Добавить в сервис `api`:
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

`curl` в `python:3.12-slim` нет; использовать stdlib `urllib`, чтобы не тащить пакеты в Dockerfile. Внутренний порт 8000, внешний 8777 — health бьёт по локальному.

---

## 7. `.dockerignore`

**Новый файл:** `.dockerignore`

Содержимое:
```
.git
.gitignore
.env
.env.example
logs/
tests/
docs/
*.md
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
.claude/
```

Ускоряет билд, защищает от случайного попадания `.env` в образ. Bind-mount в compose не затрагивается (он работает на этапе runtime, а не build).

---

## Open questions

Один вопрос требует подтверждения от пользователя перед реализацией пункта 5 (Ollama enrichment) — см. AskUserQuestion ниже либо в обсуждении после approve.

---

## Verification

1. `grep -in anthropic README.md RULES.md` → пусто.
2. `grep -rn "request.client.host" src/` → пусто (вне нового helper).
3. `grep -rn "config.get(\"headers\", {})" src/providers/` → пусто.
4. Прогнать unit-тесты: `python -m pytest tests/unit/ -v` — должны пройти все.
5. Поднять сервис: `docker compose up -d --build`, дождаться `docker compose ps` со статусом `healthy` (≤45s).
6. Проверить `curl http://localhost:8777/v1/models -H "Authorization: Bearer dummy"` — список моделей.
7. Проверить enrichment Ollama: `curl http://localhost:8777/v1/models/<ollama-model> -H "Authorization: Bearer dummy"` — либо вернёт обогащённые данные, либо warning в логах без 5xx.
8. Симулировать `request.client = None`: pytest юнит на `_client_host` (опционально, фикс однострочный).

## Files modified

- [README.md](README.md) — пункт 1
- [RULES.md](RULES.md) — пункт 1
- [src/api/main.py](src/api/main.py) — пункт 2
- [src/providers/base.py](src/providers/base.py) — пункты 3, 4
- [src/services/model_service.py](src/services/model_service.py) — пункт 5
- [docker-compose.yml](docker-compose.yml) — пункт 6
- `.dockerignore` (новый) — пункт 7
