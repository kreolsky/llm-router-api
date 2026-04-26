---
name: deploy-server
description: >
  Use when the user asks to deploy, update, ship, push to server,
  "обнови сервер", "задеплой", "выкати на прод", "deploy", "push to docker host".
  Синкает src/ на удалённый Docker-хост через rsync и перезапускает контейнер.
  Различает code-only update и full rebuild по тому, что изменилось.
  Do NOT use for: локальный docker compose up, изменения конфигов на сервере
  (config/ и .env на сервере — authoritative и не трогаются).
---

# deploy-server: обновление nnp-ai-router на удалённом Docker-хосте

## Контекст

- **Хост:** `ssh docker` (alias)
- **Путь на сервере:** `/home/serge/docker/server-ai-api`
- **Контейнер:** `server-ai-api-api-1`
- **Порт:** 8777 (host) → 8000 (container)
- **Без git** — файлы синкаются напрямую rsync'ом.
- **Volume mount** `./src:/app/src` — изменения в `src/` подхватываются после restart.

**Важно:** `config/` и `.env` на сервере — authoritative.
- Никогда не rsync-ать корень проекта.
- Никогда не пушить локальные `config/*.yaml` или `.env`.
- На сервере другие провайдеры и ключи, чем локально (`dummy` там не работает).

## Алгоритм

### Шаг 1. Pre-deploy: проверить, что изменилось

```bash
git status --short
git diff --stat HEAD requirements.txt Dockerfile
```

Развилка:
- Изменён только `src/` → **code-only update** (Шаг 3a).
- Изменены `requirements.txt` или `Dockerfile` → **full rebuild** (Шаг 3b).
- Изменены `config/` → **остановиться и спросить пользователя** (это authoritative на сервере).

### Шаг 2. Проверить состояние сервера

```bash
ssh docker "docker logs server-ai-api-api-1 --tail 5"
```

Если контейнер мёртв или сыпет ошибками — показать пользователю и подтвердить деплой.

Опционально (когда подозреваешь рассинхрон зависимостей):

```bash
ssh docker "cat /home/serge/docker/server-ai-api/requirements.txt" | diff - requirements.txt
```

Если diff есть, а локально `requirements.txt` не менялся — на сервере что-то руками поменяли, **остановиться и спросить**.

### Шаг 3a. Code-only update

```bash
rsync -av --delete src/ docker:/home/serge/docker/server-ai-api/src/
ssh docker "cd /home/serge/docker/server-ai-api && docker compose restart"
```

### Шаг 3b. Full rebuild (только если менялись requirements/Dockerfile)

```bash
rsync -av --delete src/ docker:/home/serge/docker/server-ai-api/src/
scp requirements.txt docker:/home/serge/docker/server-ai-api/
scp Dockerfile docker:/home/serge/docker/server-ai-api/
ssh docker "cd /home/serge/docker/server-ai-api && docker compose up --build -d"
```

### Шаг 4. Verify

```bash
sleep 3 && ssh docker "docker logs server-ai-api-api-1 --tail 20"
```

Должно быть:
- `Configuration manager initialized` — конфиги загрузились.
- `Application startup complete` — стартанули все воркеры (uvicorn запускает 4).
- Нет `Traceback`, `ImportError`, `ModuleNotFoundError`.

Если ошибки — показать пользователю tail-50 и не считать деплой успешным.

## Правила

- **Никогда** не rsync-ать корень проекта или `config/`/`.env` — затрёт прод-конфиги.
- **Никогда** не запускать `docker compose down` на сервере без явной просьбы — рестарт достаточно для code-only.
- **Не использовать** `docker compose up --build` для code-only изменений — лишние 1-2 минуты на пересборку, при этом ничего не меняется (volume mount уже даёт код).
- Если pre-deploy проверка показывает, что сервер мёртв или нездоров — спросить пользователя, прежде чем накатывать.
- **Не использовать `--no-verify`** или другие обходы при `git`-операциях, если они вдруг возникнут в процессе.

## Отчёт пользователю

Краткий отчёт:

```
Synced src/ → docker:/home/serge/docker/server-ai-api/src/
Restarted container, N workers up clean
```

При full rebuild — упомянуть, что пересобрался образ.
При ошибках — показать релевантные строки логов.
