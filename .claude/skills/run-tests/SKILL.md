---
name: run-tests
description: >
  Use when the user asks to run tests, "прогони тесты", "запусти тесты",
  "проверь тесты", "run pytest", "run all tests", "test the project".
  Запускает полный набор тестов (unit + API). Поднимает сервис в Docker
  при необходимости, ждёт /health, прогоняет pytest, оставляет сервис
  работающим (если был поднят), либо гасит — по выбору пользователя.
  Do NOT use for: точечный запуск одного теста, debugging без полного прогона.
---

# run-tests: полный прогон тестов nnp-ai-router

## Контекст

В проекте два слоя тестов:

- **`tests/unit/`** — изолированные unit-тесты, бегут offline за ~0.5 сек.
- **`tests/api/`** — end-to-end интеграционные, бьют по `http://localhost:8777`
  через [tests/conftest.py:17](tests/conftest.py#L17). Без живого сервиса
  падают на `httpx.ConnectError` (фикстура `skip_if_service_unavailable`
  существует, но не `autouse` — игнорируется).

Полный прогон ≈ 2 минуты (API-тесты ходят к реальным провайдерам через ключи из `.env`).

## Алгоритм

### Шаг 1. Проверить, поднят ли сервис

```bash
curl -sf http://localhost:8777/health
```

- Если `200 ok` — сервис уже работает, **не трогай docker**, переходи к шагу 3.
- Если нет — запоминаем `STARTED_BY_SKILL=1` и идём в шаг 2.

### Шаг 2. Поднять сервис в Docker

```bash
docker compose up -d --build
```

Подождать готовности (Monitor с условием, без поллинг-сна):

```bash
until curl -sf http://localhost:8777/health > /dev/null 2>&1; do sleep 2; done
```

Если за 60 сек не поднялся — `docker compose logs api | tail -50`,
показать ошибку пользователю, остановиться.

### Шаг 3. Прогнать тесты

```bash
python -m pytest tests/ --tb=short
```

Таймаут команды — **600000 мс** (10 мин), полный прогон ≈ 2 мин,
запас для медленной сети.

### Шаг 4. Гасить сервис?

- Если `STARTED_BY_SKILL=1` (мы сами подняли) — остановить:
  ```bash
  docker compose down
  ```
- Если сервис был уже поднят до запуска скилла — **не трогать**.

## Правила

- Никогда не запускай `docker compose down`, если сервис уже работал
  до старта скилла — пользователь может работать с ним параллельно.
- Никогда не используй `--no-cache` при `docker compose up` — это лишние
  10+ минут пересборки. Bind-mount на `./src` уже даёт hot-reload кода.
- Не запускай только `tests/unit/` — это «дешёвый зелёный сигнал»,
  который маскирует поломки в реальной интеграции с провайдерами.
- Если `pytest` падает на API-тестах с `ConnectError`, перепроверь
  `/health` и `docker compose ps` — возможно контейнер упал в процессе.

## Verification

После прогона проверить, что:

1. `298 passed, 1 skipped` (по состоянию на 2026-04-26) — текущее ожидаемое число.
   Skip — известный преекзистинговый в `test_models_endpoints.py`.
2. В выводе нет `FAILED` или `ERROR`.
3. Если поднимали Docker — после `compose down` `docker compose ps` пуст.

## Отчёт пользователю

Краткий отчёт в формате:

```
N passed, M skipped, K failed за T сек
```

При падениях — список `FAILED ...` строк из вывода pytest, без полного traceback.
