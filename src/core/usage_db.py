"""SQLite-backed request/usage tracking for the /stat/ dashboard.

ARCH: exactly one INSERT per request. The pure-ASGI RequestLoggerMiddleware
creates a per-request RequestStats holder in scope state, services only enrich
the holder (model, provider, tokens, errors), and the middleware flushes a
single row in a ``finally`` at the end of the request lifecycle — including
SSE streams, whose generator completes before the middleware returns.

Cost is computed at flush time from merged capabilities pricing, so historical
rows do not drift when tariffs change.
"""

import os
import time
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiosqlite

from .logging import logger

DB_PATH = os.environ.get("USAGE_DB_PATH", "data/usage.db")

_connection: aiosqlite.Connection | None = None

# ARCH: fire-and-forget flush tasks are tracked here so they are not
# garbage-collected before completion. Each task removes itself via a done
# callback that logs a WARNING on unexpected failure.
_usage_tasks: set[asyncio.Task] = set()

# Stored error messages are truncated to this length.
_MAX_ERROR_MESSAGE = 500

# Sentinel for the NULL error_code bucket in query filters (real error codes
# are lowercase snake_case, so this cannot collide).
ERROR_CODE_NULL = "none"

# Error predicate: an error is an error status OR any recorded error_code
# (a mid-stream SSE failure keeps HTTP 200 but carries error_code).
_ERR_SQL = "(status_code >= 400 OR error_code IS NOT NULL)"

# Additive migration: columns added by the usage-stats redesign, applied over
# an existing DB via ALTER TABLE (driven by PRAGMA table_info in init_db).
_MIGRATIONS: Dict[str, str] = {
    "error_code": "TEXT",
    "error_message": "TEXT",
    "api_key_hash": "TEXT",
    "client_ip": "TEXT",
    "reasoning_tokens": "INTEGER NOT NULL DEFAULT 0",
    "cost_usd": "REAL",
    # Default asymmetry is intentional: the column default is 1 so that
    # pre-existing rows (which always had usage) read correctly, while
    # RequestStats.has_usage defaults to False in Python and is set to True
    # only inside set_usage().
    "has_usage": "INTEGER NOT NULL DEFAULT 1",
    "stream": "INTEGER NOT NULL DEFAULT 0",
}


# ---------------------------------------------------------------------------
# Per-request holder
# ---------------------------------------------------------------------------

@dataclass
class RequestStats:
    """Mutable per-request stats, stored in scope["state"]["request_stats"].

    Created by the middleware, enriched by services/auth, flushed exactly once
    by the middleware at the end of the request.
    """

    endpoint: str = ""
    client_ip: str = ""
    model_id: str = ""
    provider_name: str = ""
    stream: bool = False
    has_usage: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    api_key_hash: Optional[str] = None

    def set_usage(self, usage: Dict[str, Any]) -> None:
        """Single token-extraction point for the provider usage shape.

        The only place that reads ``prompt_tokens_details.cached_tokens`` and
        ``completion_tokens_details.reasoning_tokens``, so the stream and
        non-stream field sets cannot drift.
        """
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        self.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        self.completion_tokens = int(usage.get("completion_tokens") or 0)
        self.cached_tokens = int(prompt_details.get("cached_tokens") or 0)
        self.reasoning_tokens = int(completion_details.get("reasoning_tokens") or 0)
        self.total_tokens = int(usage.get("total_tokens") or 0)
        self.has_usage = True


def request_stats(request: Optional[object]) -> RequestStats:
    """Read the RequestStats set by middleware, or a fresh throwaway holder.

    Tolerates a missing request and a request that never passed through the
    middleware (unit tests, ASGI lifespan), so callers never branch on None.
    The throwaway is created per call — the holder is mutable, so a shared
    one would leak enrichment between requests.
    """
    if request is None:
        return RequestStats()
    stats = getattr(getattr(request, "state", None), "request_stats", None)
    return stats if isinstance(stats, RequestStats) else RequestStats()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

async def init_db() -> None:
    global _connection
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    _connection = await aiosqlite.connect(DB_PATH)
    await _connection.execute("PRAGMA journal_mode=WAL")
    # WHY: WAL allows one writer at a time. Without a busy timeout a concurrent
    # writer (another uvicorn worker, or the sqlite3 CLI during an inspection)
    # makes the write fail instantly with "database is locked" — and the
    # failure is swallowed by _flush_row, so usage events would vanish in
    # silence.
    await _connection.execute("PRAGMA busy_timeout=5000")
    await _connection.execute(f"""
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
            status_code INTEGER,
            error_code TEXT,
            error_message TEXT,
            api_key_hash TEXT,
            client_ip TEXT,
            reasoning_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL,
            has_usage INTEGER NOT NULL DEFAULT 1,
            stream INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Additive migration over an existing DB: existing rows are kept and read
    # with NULL/default values in the new columns.
    cursor = await _connection.execute("PRAGMA table_info(usage_events)")
    existing = {row[1] for row in await cursor.fetchall()}
    for column, decl in _MIGRATIONS.items():
        if column not in existing:
            await _connection.execute(
                f"ALTER TABLE usage_events ADD COLUMN {column} {decl}")
    # The request log is ORDER BY timestamp DESC; the existing composite index
    # starts with project_name, so it cannot serve that scan.
    await _connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_events(timestamp)")
    await _connection.commit()


async def close_db() -> None:
    global _connection
    if _connection:
        await _connection.close()
        _connection = None


def get_connection() -> Optional[aiosqlite.Connection]:
    return _connection


# ---------------------------------------------------------------------------
# Flush
# ---------------------------------------------------------------------------

# INVARIANT: stored pricing is USD PER TOKEN (OpenRouter's convention).
# model_info.yaml is hand-curated — a "per 1M tokens" value would silently
# inflate every recorded cost by 10^6, and costs are frozen at write time so
# the error would be invisible and permanent. Pinned by tests.
def _compute_cost_usd(stats: RequestStats, app_state: Optional[Any]) -> Optional[float]:
    """Write-time cost from merged capabilities pricing; None when unpriced.

    (prompt - cached) * prompt + cached * input_cache_read + completion * completion.
    A missing input_cache_read falls back to the prompt rate — stored pricing
    only contains the keys the upstream actually sent, and treating an absent
    cache rate as free would systematically under-report cost.
    """
    if stats.prompt_tokens + stats.completion_tokens <= 0:
        return None
    model_service = getattr(app_state, "model_service", None)
    if model_service is None:
        return None
    try:
        pricing = model_service.get_pricing(stats.model_id)
    except Exception:
        # Includes a missing/broken model_service during early lifespan.
        return None
    if not isinstance(pricing, dict) or not pricing:
        return None
    prompt_price = pricing.get("prompt")
    completion_price = pricing.get("completion")
    if prompt_price is None or completion_price is None:
        return None
    cache_price = pricing.get("input_cache_read", prompt_price)
    non_cached = max(stats.prompt_tokens - stats.cached_tokens, 0)
    return (non_cached * prompt_price
            + stats.cached_tokens * cache_price
            + stats.completion_tokens * completion_price)


async def _flush_row(
    stats: RequestStats,
    *,
    request_id: str,
    project_name: str,
    duration_ms: float,
    status_code: int,
    app_state: Optional[Any],
) -> None:
    """Insert the single usage_events row for a finished request.

    NOT NULL fallbacks: a 401 knows no project/model/provider, so the flush
    substitutes "unknown" / "" — without this the INSERT raises and the
    failure is swallowed below, i.e. errors would silently not be recorded.
    """
    cost_usd = _compute_cost_usd(stats, app_state)
    error_message = stats.error_message[:_MAX_ERROR_MESSAGE] if stats.error_message else None
    try:
        conn = get_connection()
        if conn is None:
            return
        await conn.execute(
            """INSERT INTO usage_events
               (request_id, project_name, model_id, provider_name, endpoint,
                timestamp, prompt_tokens, completion_tokens, cached_tokens,
                reasoning_tokens, total_tokens, duration_ms, status_code,
                error_code, error_message, api_key_hash, client_ip,
                cost_usd, has_usage, stream)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id,
                project_name or "unknown",
                stats.model_id or "",
                stats.provider_name or "",
                stats.endpoint,
                time.time(),
                stats.prompt_tokens,
                stats.completion_tokens,
                stats.cached_tokens,
                stats.reasoning_tokens,
                stats.total_tokens,
                duration_ms,
                status_code,
                stats.error_code,
                error_message,
                stats.api_key_hash,
                stats.client_ip or "",
                cost_usd,
                1 if stats.has_usage else 0,
                1 if stats.stream else 0,
            ),
        )
        await conn.commit()
    except Exception as e:
        # WHY: the flush runs on every request; a sustained DB outage would
        # otherwise flood logs. Throttle to a summary once per minute.
        global _last_usage_error_logged
        now = time.time()
        if now - _last_usage_error_logged >= _USAGE_ERROR_LOG_INTERVAL:
            _last_usage_error_logged = now
            logger.error(
                f"Failed to record usage: {e}",
                extra={
                    "log_type": "error",
                    "error_type": "usage_recording_error",
                    "request_id": request_id,
                    "model_id": stats.model_id,
                    "endpoint": stats.endpoint,
                },
                exc_info=True,
            )


# Last wall-clock timestamp at which a flush error was logged at full detail.
# Used to throttle logging during a DB outage.
_last_usage_error_logged: float = 0.0
_USAGE_ERROR_LOG_INTERVAL: float = 60.0


def _on_usage_done(task: asyncio.Task) -> None:
    """Done callback: discard the task and log WARNING on failure."""
    _usage_tasks.discard(task)
    exc = task.exception()
    if exc is not None:
        logger.warning(
            f"Usage recording task failed: {exc}",
            extra={
                "log_type": "warning",
                "error_type": "usage_task_failure",
                "error_message": str(exc),
            },
            exc_info=exc,
        )


def schedule_flush(
    stats: RequestStats,
    *,
    request_id: str,
    project_name: str,
    duration_ms: float,
    status_code: int,
    app_state: Optional[Any],
) -> Optional[asyncio.Task]:
    """Fire-and-forget single-row flush (tracked in _usage_tasks).

    Returns the created task, or None when no event loop is running. Flush
    tasks created during shutdown after close_db() see a None connection and
    no-op — a bounded loss window at process exit, accepted.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(_flush_row(
        stats,
        request_id=request_id,
        project_name=project_name,
        duration_ms=duration_ms,
        status_code=status_code,
        app_state=app_state,
    ))
    _usage_tasks.add(task)
    task.add_done_callback(_on_usage_done)
    return task


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _filter_where(
    users: List[str],
    models: List[str],
    days: Optional[int],
    extra_conditions: Optional[List[str]] = None,
    extra_params: Optional[list] = None,
) -> tuple[str, list]:
    """Build the shared WHERE clause (users/models/days + extras)."""
    conditions = list(extra_conditions or [])
    params: list = list(extra_params or [])

    if users:
        placeholders = ",".join("?" for _ in users)
        conditions.append(f"project_name IN ({placeholders})")
        params.extend(users)

    if models:
        placeholders = ",".join("?" for _ in models)
        conditions.append(f"model_id IN ({placeholders})")
        params.extend(models)

    if days is not None:
        conditions.append("timestamp >= ?")
        params.append(time.time() - days * 86400)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params


async def get_distinct_users() -> List[str]:
    conn = get_connection()
    if conn is None:
        return []
    cursor = await conn.execute(
        "SELECT DISTINCT project_name FROM usage_events ORDER BY project_name"
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_distinct_models() -> List[str]:
    conn = get_connection()
    if conn is None:
        return []
    cursor = await conn.execute(
        "SELECT DISTINCT model_id FROM usage_events ORDER BY model_id"
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_usage_data(
    users: List[str],
    models: List[str],
    days: Optional[int],
) -> dict:
    conn = get_connection()
    if conn is None:
        return {"series": []}

    where, params = _filter_where(users, models, days)

    query = f"""
        SELECT
            project_name,
            model_id,
            date(timestamp, 'unixepoch') AS day,
            SUM(prompt_tokens) AS prompt,
            SUM(cached_tokens) AS cached,
            SUM(completion_tokens) AS completion
        FROM usage_events
        {where}
        GROUP BY project_name, model_id, day
        ORDER BY project_name, model_id, day
    """

    cursor = await conn.execute(query, params)
    rows = await cursor.fetchall()

    series_map: dict[tuple[str, str], dict] = {}
    all_dates: set[str] = set()

    for project_name, model_id, day, prompt, cached, completion in rows:
        key = (project_name, model_id)
        if key not in series_map:
            series_map[key] = {
                "user": project_name,
                "model": model_id,
                "dates": [],
                "prompt": [],
                "cached": [],
                "completion": [],
            }
        series_map[key]["dates"].append(day)
        series_map[key]["prompt"].append(prompt)
        series_map[key]["cached"].append(cached)
        series_map[key]["completion"].append(completion)
        all_dates.add(day)

    sorted_dates = sorted(all_dates)

    series = []
    for s in series_map.values():
        date_map = dict(zip(s["dates"], zip(s["prompt"], s["cached"], s["completion"])))
        aligned_prompt = []
        aligned_cached = []
        aligned_completion = []
        for d in sorted_dates:
            if d in date_map:
                p, c, comp = date_map[d]
                aligned_prompt.append(p)
                aligned_cached.append(c)
                aligned_completion.append(comp)
            else:
                aligned_prompt.append(0)
                aligned_cached.append(0)
                aligned_completion.append(0)
        series.append({
            "user": s["user"],
            "model": s["model"],
            "dates": sorted_dates,
            "prompt": aligned_prompt,
            "cached": aligned_cached,
            "completion": aligned_completion,
        })

    return {"series": series}


def _empty_summary() -> dict:
    return {
        "totals": {
            "requests": 0,
            "errors": 0,
            "error_rate": 0.0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "cost_usd": None,
            "unpriced": 0,
            "cache_hit_rate": 0.0,
        },
        "by_user": [],
        "by_model": [],
        "by_provider": [],
        "by_error_code": [],
        "by_day": [],
    }


async def get_summary(users: List[str], models: List[str], days: Optional[int]) -> dict:
    """Totals plus breakdowns for the dashboard.

    cache_hit_rate = Σcached / Σprompt; rows with has_usage = 0 contribute 0
    to both sides. An empty selection returns zeros, never a division by zero.
    cost_usd sums only priced rows (NULL when none); unpriced counts rows that
    carried tokens but have no recorded cost.
    """
    conn = get_connection()
    if conn is None:
        return _empty_summary()

    where, params = _filter_where(users, models, days)
    err = _ERR_SQL

    cursor = await conn.execute(f"""
        SELECT COUNT(*),
               SUM(CASE WHEN {err} THEN 1 ELSE 0 END),
               SUM(prompt_tokens), SUM(cached_tokens), SUM(completion_tokens),
               SUM(reasoning_tokens), SUM(total_tokens), SUM(cost_usd),
               SUM(CASE WHEN cost_usd IS NULL AND prompt_tokens + completion_tokens > 0
                        THEN 1 ELSE 0 END)
        FROM usage_events {where}
    """, params)
    (requests, errors, prompt, cached, completion, reasoning, total, cost, unpriced) = \
        await cursor.fetchone()

    requests = requests or 0
    errors = errors or 0
    prompt = prompt or 0
    cached = cached or 0
    completion = completion or 0
    reasoning = reasoning or 0
    total = total or 0

    async def _breakdown(dimension: str, label: str) -> List[dict]:
        cursor = await conn.execute(f"""
            SELECT {dimension} AS dim,
                   COUNT(*),
                   SUM(CASE WHEN {err} THEN 1 ELSE 0 END),
                   SUM(prompt_tokens), SUM(cached_tokens),
                   SUM(completion_tokens), SUM(total_tokens), SUM(cost_usd)
            FROM usage_events {where}
            GROUP BY dim
            ORDER BY SUM(total_tokens) DESC
        """, params)
        rows = await cursor.fetchall()
        return [
            {
                label: row[0],
                "requests": row[1],
                "errors": row[2] or 0,
                "prompt_tokens": row[3] or 0,
                "cached_tokens": row[4] or 0,
                "completion_tokens": row[5] or 0,
                "total_tokens": row[6] or 0,
                "cost_usd": row[7],
            }
            for row in rows
        ]

    # Errors only (NULL error_code bucket = errors that bypassed the
    # enrichment point: 422s, disconnects, string-detail 404s).
    cursor = await conn.execute(f"""
        SELECT error_code, COUNT(*)
        FROM usage_events {where}{' AND ' + err if where else ' WHERE ' + err}
        GROUP BY error_code
        ORDER BY COUNT(*) DESC
    """, params)
    by_error_code = [
        {"error_code": row[0], "count": row[1]} for row in await cursor.fetchall()
    ]

    cursor = await conn.execute(f"""
        SELECT date(timestamp, 'unixepoch') AS day,
               COUNT(*),
               SUM(CASE WHEN {err} THEN 1 ELSE 0 END),
               SUM(prompt_tokens), SUM(cached_tokens), SUM(completion_tokens),
               SUM(cost_usd)
        FROM usage_events {where}
        GROUP BY day
        ORDER BY day
    """, params)
    by_day = [
        {
            "day": row[0],
            "requests": row[1],
            "errors": row[2] or 0,
            "prompt_tokens": row[3] or 0,
            "cached_tokens": row[4] or 0,
            "completion_tokens": row[5] or 0,
            "cost_usd": row[6],
        }
        for row in await cursor.fetchall()
    ]

    return {
        "totals": {
            "requests": requests,
            "errors": errors,
            "error_rate": (errors / requests) if requests else 0.0,
            "prompt_tokens": prompt,
            "cached_tokens": cached,
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
            "total_tokens": total,
            "cost_usd": cost,
            "unpriced": unpriced or 0,
            "cache_hit_rate": (cached / prompt) if prompt else 0.0,
        },
        "by_user": await _breakdown("project_name", "user"),
        "by_model": await _breakdown("model_id", "model"),
        "by_provider": await _breakdown("provider_name", "provider"),
        "by_error_code": by_error_code,
        "by_day": by_day,
    }


async def get_requests(
    users: List[str],
    models: List[str],
    providers: List[str],
    status: str,
    error_code: str,
    request_id: str,
    days: Optional[int],
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Newest-first request log with filters and pagination."""
    conn = get_connection()
    if conn is None:
        return {"requests": [], "total": 0}

    conditions: List[str] = []
    params: list = []

    if status == "ok":
        conditions.append(f"NOT {_ERR_SQL}")
    elif status == "error":
        conditions.append(_ERR_SQL)

    if error_code == ERROR_CODE_NULL:
        # The NULL bucket means error rows whose error_code is NULL (422s,
        # disconnects) — success rows have NULL too but are not errors.
        conditions.append(f"error_code IS NULL AND {_ERR_SQL}")
    elif error_code:
        conditions.append("error_code = ?")
        params.append(error_code)

    if request_id:
        conditions.append("request_id = ?")
        params.append(request_id)

    if providers:
        placeholders = ",".join("?" for _ in providers)
        conditions.append(f"provider_name IN ({placeholders})")
        params.extend(providers)

    where, params = _filter_where(users, models, days, conditions, params)

    cursor = await conn.execute(
        f"SELECT COUNT(*) FROM usage_events {where}", params)
    (total,) = await cursor.fetchone()

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    cursor = await conn.execute(f"""
        SELECT id, request_id, timestamp, project_name, model_id, provider_name,
               endpoint, stream, prompt_tokens, completion_tokens, cached_tokens,
               reasoning_tokens, total_tokens, cost_usd, duration_ms, status_code,
               error_code, error_message, api_key_hash, client_ip
        FROM usage_events {where}
        ORDER BY timestamp DESC, id DESC
        LIMIT ? OFFSET ?
    """, [*params, limit, offset])
    rows = await cursor.fetchall()

    return {
        "requests": [
            {
                "id": row[0],
                "request_id": row[1],
                "timestamp": row[2],
                "project_name": row[3],
                "model_id": row[4],
                "provider_name": row[5],
                "endpoint": row[6],
                "stream": bool(row[7]),
                "prompt_tokens": row[8],
                "completion_tokens": row[9],
                "cached_tokens": row[10],
                "reasoning_tokens": row[11],
                "total_tokens": row[12],
                "cost_usd": row[13],
                "duration_ms": row[14],
                "status_code": row[15],
                "error_code": row[16],
                "error_message": row[17],
                "api_key_hash": row[18],
                "client_ip": row[19],
            }
            for row in rows
        ],
        "total": total,
    }
