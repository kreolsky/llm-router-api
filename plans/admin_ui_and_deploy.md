# Admin UI + Gitea Actions Auto-Deploy

## Context
Нужны: (1) автодеплой через Gitea Actions, (2) веб-интерфейс для редактирования YAML-конфигов в реальном времени. Hot-reload уже работает — ConfigManager поллит mtimes каждые 5 секунд. UI максимально простой — текстовые редакторы YAML + кнопка генерации ключа.

## Проблема
Конфиги в git. Автодеплой при каждом push пересобирает контейнер. Но конфиги на сервере могут отличаться от git (редактировали через UI). Решение: Docker named volume для config — конфиги живут в volume, переживают деплои. Admin UI редактирует файлы внутри volume.

---

## Part 1: Auto-Deploy (Gitea Actions)

### `.gitea/workflows/deploy.yml` (new)

По образцу из `.material/deploy.yml`. На push в main: clone → write .env из secrets → docker compose up.

```yaml
name: Deploy to Production

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    container:
      image: python:3.12-slim

    steps:
      - name: Install tools
        run: apt-get update && apt-get install -y docker-cli docker-compose-v2 git

      - name: Checkout
        run: git clone --depth=1 "https://oauth2:${{ github.token }}@git.box.nnp.space/${{ github.repository }}.git" .

      - name: Write .env
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          ORANGE_API_KEY: ${{ secrets.ORANGE_API_KEY }}
          ZAI_API_KEY: ${{ secrets.ZAI_API_KEY }}
          KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}
          TRANSCRIPTIONS_API_KEY: ${{ secrets.TRANSCRIPTIONS_API_KEY }}
          ADMIN_API_KEY: ${{ secrets.ADMIN_API_KEY }}
        run: |
          for key in OPENAI_API_KEY DEEPSEEK_API_KEY OPENROUTER_API_KEY ORANGE_API_KEY ZAI_API_KEY KIMI_API_KEY TRANSCRIPTIONS_API_KEY ADMIN_API_KEY; do
            eval val=\$$key
            [ -n "$val" ] && echo "$key=$val" >> .env
          done

      - name: Deploy
        run: docker compose -p nnp-ai-router up -d --build
```

### Docker named volume для config

```yaml
# docker-compose.yml
services:
  api:
    volumes:
      - config_data:/app/config   # named volume, persists across deploys
      - ./src:/app/src
      - ./logs:/app/logs

volumes:
  config_data:
```

При первом деплое config из образа копируется в volume. При последующих — volume уже есть, конфиги сохраняются. Admin UI редактирует файлы внутри volume.

---

## Part 2: Admin UI

### Концепция

Минималистичный веб-интерфейс:
- 3 текстовых редактора (textarea) для прямого редактирования YAML: providers, models, user_keys
- Кнопка "Save" у каждого → PUT на API → пишет файл → hot-reload подхватывает
- Кнопка "Generate Key" → вызывает `/tools/generate_key` → показывает ключ
- Защита: `ADMIN_API_KEY` из .env

### New Files

| File | Purpose |
|---|---|
| `src/core/admin_auth.py` | `verify_admin_key` — dependency, проверяет `ADMIN_API_KEY` env var |
| `src/api/admin.py` | APIRouter: GET/PUT для каждого конфиг-файла как raw YAML |
| `src/admin_ui/index.html` | SPA: 3 YAML-редактора + Generate Key |
| `src/admin_ui/style.css` | Минимальный CSS |
| `src/admin_ui/app.js` | Fetch API client, textarea logic |

### Modified Files

| File | Change |
|---|---|
| `src/api/main.py` | Include admin_router, mount StaticFiles `/admin/` |
| `docker-compose.yml` | Named volume для config |
| `.env` | Add `ADMIN_API_KEY` |

---

### `src/core/admin_auth.py`

```python
async def verify_admin_key(request: Request) -> None:
    """Check Authorization: Bearer against ADMIN_API_KEY env var."""
```

Отдельно от user_keys.yaml — админ-ключ не должен управляться конфигом, который он редактирует.

### `src/api/admin.py`

```
GET  /admin/api/config/{file_name}   — содержимое YAML как text/plain
PUT  /admin/api/config/{file_name}   — принять raw YAML, записать, reload
POST /admin/api/config/reload        — принудительный reload
```

`file_name`: `providers` | `models` | `user_keys` → `config/{file_name}.yaml`.

PUT валидирует YAML перед записью. Atomic write: temp file → os.replace. Backup: .bak.

### `src/admin_ui/`

**index.html:** Login form (admin key → sessionStorage). 3 таба с textarea. Save + Generate Key.

**app.js:** GET конфигов → textarea. Save → PUT. Generate Key → GET `/tools/generate_key`.

**style.css:** Моноширинный шрифт, `border-radius: 0`.

---

## Implementation Order

1. `src/core/admin_auth.py`
2. `src/api/admin.py`
3. Wire into `main.py`
4. `src/admin_ui/`
5. `.gitea/workflows/deploy.yml`
6. Unit tests
7. `docker-compose.yml` — named volume

## Verification

1. `python -m pytest tests/unit/ -v` — existing tests pass
2. `curl -H "Authorization: Bearer $ADMIN_API_KEY" localhost:8777/admin/api/config/models` — returns YAML
3. PUT new YAML → verify hot-reload picked it up via `/v1/models`
4. Open `localhost:8777/admin/` → login → edit → save → verify
5. Generate Key button works
