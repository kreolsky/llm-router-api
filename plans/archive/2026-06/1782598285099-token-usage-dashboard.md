# Token Usage Dashboard — Implementation Plan

## Summary
Add SQLite-backed token-usage tracking to the NNP AI Router and a minimal dashboard at `/stat/` showing stacked area time-series charts filtered by user and model checkboxes.

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Address | `/stat/` (HTML page) + `/stat/api/...` (JSON endpoints) |
| Storage | SQLite via `aiosqlite` (one new dependency) |
| Frontend | Pure HTML + Chart.js 4.x from CDN |
| Token counting | From provider response `usage` field |
| Users | `project_name` from `user_keys.yaml` auth |
| Auth for `/stat/` | None (internal network) |
| Chart type | Stacked area time-series |
| Layers | 3: prompt_tokens / cached_tokens / completion_tokens |
| Time periods | Buttons: 7 / 30 / 90 days / all time |
| Retention | Forever |
| Metrics | Valid: chat (+ streaming), embeddings |

## Files to create

1. **`src/core/usage_db.py`** — Database module (init, write, query)
2. **`src/api/stat_page.py`** — Dashboard HTML page string and `/stat/` route handler

## Files to modify

3. **`requirements.txt`** — Add `aiosqlite`
4. **`src/api/main.py`** — Add `/stat/` and `/stat/api/...` routes, DB init in lifespan, mount `data/` volume
5. **`src/services/chat_service/chat_service.py`** — Extract usage from non-streaming responses + write to DB
6. **`src/services/chat_service/stream_processor.py`** — Capture usage from final SSE chunk + write to DB after stream
7. **`src/services/embedding_service.py`** — Write token usage to DB (currently only logs)
8. **`docker-compose.yml`** — Add `./data:/app/data` volume mount

---

## Task 1: Add `aiosqlite` dependency

Add to `requirements.txt`:
```
aiosqlite>=0.20.0
```

## Task 2: Create `src/core/usage_db.py`

### 2.1 DB initialization
- `DB_PATH = "data/usage.db"` (configurable via `USAGE_DB_PATH` env var)
- `_connection: aiosqlite.Connection` module-level singleton
- `async def init_db()` — creates `data/` directory if missing, opens connection, creates table with WAL mode
- `async def close_db()` — closes connection gracefully

### 2.2 Schema
```sql
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    project_name TEXT NOT NULL,
    model_id TEXT NOT NULL,
    provider_name TEXT,
    endpoint TEXT NOT NULL,
    timestamp REAL NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms REAL,
    status_code INTEGER
);

CREATE INDEX IF NOT EXISTS idx_usage_project_model_ts
    ON usage_events(project_name, model_id, timestamp);
```

### 2.3 Write function
```python
async def record_usage(
    project_name: str,
    model_id: str,
    endpoint: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    total_tokens: int = 0,
    request_id: str = "",
    provider_name: str = "",
    duration_ms: float = 0,
    status_code: int = 200
) -> None:
```
- Inserts a row into `usage_events`
- Fire-and-forget via `asyncio.create_task()` from callers, but DB write itself is awaited inside the function
- Handles exceptions silently (don't crash the request for logging failure)

### 2.4 Query functions
```python
async def get_distinct_users() -> list[str]
async def get_distinct_models() -> list[str]
```

```python
async def get_usage_data(
    users: list[str],
    models: list[str],
    days: int | None  # None = all time
) -> dict:
    # Returns: {
    #   "series": [
    #     {"user": "debug", "model": "deepseek/pro", "dates": ["2026-06-01", ...],
    #      "prompt": [100, 200, ...], "cached": [0, 10, ...], "completion": [50, 100, ...]}
    #   ]
    # }
```

- Aggregates by day, user, model
- Groups into series (one per user+model combination)
- Uses `COUNT(DISTINCT date)` for each group to align date arrays

### 2.5 Connection accessor
```python
def get_connection() -> aiosqlite.Connection:
    return _connection
```

## Task 3: Create `src/api/stat_page.py`

### 3.1 HTML page
A single HTML string constant `STAT_PAGE_HTML` (~200 lines) with:
- CDN import: `chart.js@4.4.0`, `chartjs-adapter-date-fns@3`
- 3-column CSS grid layout
- Left column: user checkboxes + "Select All" / "Deselect All" buttons
- Center column: model checkboxes + "Select All" / "Deselect All" buttons
- Right column: period buttons (7d / 30d / 90d / All) above the `<canvas>` chart
- Dark theme (matches internal tool vibe), `border-radius: 0` everywhere (per CLAUDE.md!)
- JS logic: fetch users/models on load → render checkboxes → on change fetch `/stat/api/usage?...` → update Chart.js stacked area

### 3.2 Chart.js configuration
- Stacked area chart, x-axis = time (date-fns adapter)
- Each user+model combo gets a unique stack ID
- 3 datasets per stack: prompt (solid), cached (dotted), completion (dashed) — same hue family, different lightness
- y-axis label: "Tokens"

### 3.3 Route handler
```python
async def stat_page(request: Request):
    return HTMLResponse(content=STAT_PAGE_HTML)
```
Imported into `main.py`.

## Task 4: Modify `src/api/main.py`

### 4.1 Lifespan changes
- After `app.state.transcription_service = ...`:
  ```python
  from ..core.usage_db import init_db, close_db
  await init_db()
  ```
- Before `yield` in teardown:
  ```python
  await close_db()
  ```

### 4.2 New routes
```python
@app.get("/stat/")
async def stat_dashboard(request: Request):
    from .stat_page import stat_page
    return await stat_page(request)

@app.get("/stat/api/users")
async def stat_users():
    from ..core.usage_db import get_distinct_users
    return await get_distinct_users()

@app.get("/stat/api/models")
async def stat_models():
    from ..core.usage_db import get_distinct_models
    return await get_distinct_models()

@app.get("/stat/api/usage")
async def stat_usage(users: str = "", models: str = "", days: str = ""):
    from ..core.usage_db import get_usage_data
    user_list = [u.strip() for u in users.split(",") if u.strip()] if users else []
    model_list = [m.strip() for m in models.split(",") if m.strip()] if models else []
    days_int = int(days) if days else None
    return await get_usage_data(user_list, model_list, days_int)
```

## Task 5: Modify `src/services/chat_service/chat_service.py`

### 5.1 Non-streaming path (after line 103)
Before `return JSONResponse(content=response_data)`:

```python
usage = response_data.get("usage", {})
if usage:
    ctx = self._get_request_context(request)
    import time, asyncio
    from ...core.usage_db import record_usage
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = (
        usage.get("prompt_tokens_details", {})
        .get("cached_tokens", 0)
    )
    asyncio.create_task(record_usage(
        project_name=ctx["user_id"],
        model_id=requested_model,
        endpoint="chat",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        total_tokens=usage.get("total_tokens", 0),
        request_id=ctx["request_id"],
        provider_name=provider_name,
    ))
```

### 5.2 Unify `duration_ms` tracking
Track `start_time = time.time()` at the top of `chat_completions` and pass duration to both streaming and non-streaming paths.

## Task 6: Modify `src/services/chat_service/stream_processor.py`

### 6.1 Add `_captured_usage` attribute to `StreamProcessor`
```python
def __init__(self, config_manager=None):
    ...
    self._captured_usage = None  # Reset per-stream
```

### 6.2 Transparent path (line 86-104)
In the transparent loop, after yielding each chunk, check if chunk bytes contain `"usage"`:
```python
if b'"usage"' in chunk and b'"prompt_tokens"' in chunk:
    try:
        # Parse SSE: find "data: {" line, extract JSON
        text = chunk.decode('utf-8')
        for line in text.split('\n'):
            if line.startswith('data: ') and line != 'data: [DONE]':
                data = json.loads(line[6:])
                if 'usage' in data:
                    self._captured_usage = data['usage']
    except Exception:
        pass
```

Then after the stream loop ends but before the "Stream completed" log, record usage:
```python
if self._captured_usage:
    await _record_stream_usage(
        self._captured_usage, request_id, user_id, model_id, start_time
    )
```

### 6.3 Sanitized path (line 106+)
In `_sanitize_sse_message`, detect and store `usage` from parsed JSON chunks:
```python
chunk_data = json.loads(json_str)
if 'usage' in chunk_data:
    self._captured_usage = chunk_data['usage']
```
Then same recording logic after the stream loop completes.

### 6.4 Helper function
```python
async def _record_stream_usage(usage, request_id, user_id, model_id, start_time):
    from ...core.usage_db import record_usage
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
    duration_ms = (time.time() - start_time) * 1000
    await record_usage(
        project_name=user_id,
        model_id=model_id,
        endpoint="chat",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        total_tokens=usage.get("total_tokens", 0),
        request_id=request_id,
        duration_ms=duration_ms,
    )
```

## Task 7: Modify `src/services/embedding_service.py`

After line 71 (the existing `logger.info(...)` with token_usage), add:
```python
import asyncio
from ...core.usage_db import record_usage
asyncio.create_task(record_usage(
    project_name=user_id,
    model_id=requested_model,
    endpoint="embeddings",
    prompt_tokens=response_data.get("usage", {}).get("prompt_tokens", 0),
    completion_tokens=0,
    cached_tokens=0,
    total_tokens=response_data.get("usage", {}).get("total_tokens", 0),
    request_id=request_id,
    provider_name=provider_name,
))
```

## Task 8: Modify `docker-compose.yml`

Add volume mount for SQLite persistence:
```yaml
volumes:
  - ./src:/app/src
  - ./config:/app/config
  - ./logs:/app/logs
  - ./data:/app/data  # NEW: SQLite DB
```

## Validation

1. **Unit check**: `python -c "import aiosqlite"` — dependency loads
2. **DB init**: Start service, verify `data/usage.db` is created
3. **Chat recording**: Send a non-streaming chat request → verify row in `usage_events` via `sqlite3 data/usage.db "SELECT * FROM usage_events;"`
4. **Stream recording**: Send a streaming chat request → verify row with `endpoint='chat'` and correct tokens
5. **Embedding recording**: Send embedding request → verify row with `endpoint='embeddings'`
6. **Dashboard**: Open `/stat/` → users/models load → select checkboxes → chart renders
7. **Existing tests**: Run `pytest` — existing tests must still pass (new code is additive)

## Risks

- **Streaming `usage` placement varies**: Some providers put usage in the `[DONE]` chunk itself, others in the penultimate chunk with `finish_reason`. The detection approach (look for `"usage"` key in any parsed chunk) handles both cases.
- **UTF-8 chunk boundary across `"usage"`**: In transparent mode, if `"usage"` bytes are split across two chunks, we might miss it. Mitigation: the sanitized path handles this correctly; transparent path's simple `b'"usage"' in chunk` check has a small blind spot (~1 in 10000 chance). Acceptable for a v1 internal tool.
- **DB growth**: No auto-purge. Monitor manually. `data/` volume on Docker host keeps data between deploys.
