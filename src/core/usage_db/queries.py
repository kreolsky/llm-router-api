"""Dashboard query side of usage tracking: every read path for /stat/api/*.

Pure reads over usage_events; shares only the connection (in _conn.py) with
the writer. The connection's row factory is aiosqlite.Row (set in init_db),
so every SELECT aliases its columns to the JSON keys the dashboard reads and a
row becomes its response object through dict(row).
"""

import time

import aiosqlite

from ._conn import get_connection

# Sentinel for the NULL error_code bucket in query filters (real error codes
# are lowercase snake_case, so this cannot collide).
ERROR_CODE_NULL = "none"

# Error predicate: an error is an error status OR any recorded error_code
# (a mid-stream SSE failure keeps HTTP 200 but carries error_code).
_ERR_SQL = "(status_code >= 400 OR error_code IS NOT NULL)"


def _filter_where(
    users: list[str],
    models: list[str],
    days: int | None,
    extra_conditions: list[str] | None = None,
    extra_params: list | None = None,
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


async def get_distinct_users() -> list[str]:
    conn = get_connection()
    if conn is None:
        return []
    cursor = await conn.execute(
        "SELECT DISTINCT project_name FROM usage_events ORDER BY project_name"
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_distinct_models() -> list[str]:
    conn = get_connection()
    if conn is None:
        return []
    cursor = await conn.execute(
        "SELECT DISTINCT model_id FROM usage_events ORDER BY model_id"
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]


async def get_usage_data(
    users: list[str],
    models: list[str],
    days: int | None,
) -> dict:
    conn = get_connection()
    if conn is None:
        return {"series": []}

    where, params = _filter_where(users, models, days)
    cursor = await conn.execute(f"""
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
    """, params)
    rows = await cursor.fetchall()

    per_series: dict[tuple[str, str], dict[str, tuple[int, int, int]]] = {}
    for row in rows:
        by_day = per_series.setdefault((row["project_name"], row["model_id"]), {})
        by_day[row["day"]] = (row["prompt"], row["cached"], row["completion"])
    sorted_dates = sorted({day for by_day in per_series.values() for day in by_day})

    return {"series": [
        _aligned_series(user, model, by_day, sorted_dates)
        for (user, model), by_day in per_series.items()
    ]}


def _aligned_series(user: str, model: str, by_day: dict[str, tuple[int, int, int]],
                    sorted_dates: list[str]) -> dict:
    """One (user, model) series over every selected day, 0 where it had no rows."""
    points = [by_day.get(day, (0, 0, 0)) for day in sorted_dates]
    return {
        "user": user,
        "model": model,
        "dates": sorted_dates,
        "prompt": [p for p, _, _ in points],
        "cached": [c for _, c, _ in points],
        "completion": [comp for _, _, comp in points],
    }


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


async def get_summary(users: list[str], models: list[str], days: int | None) -> dict:
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
    return {
        "totals": await _summary_totals(conn, where, params),
        "by_user": await _breakdown(conn, where, params, "project_name", "user"),
        "by_model": await _breakdown(conn, where, params, "model_id", "model"),
        "by_provider": await _breakdown(conn, where, params, "provider_name", "provider"),
        "by_error_code": await _by_error_code(conn, where, params),
        "by_day": await _by_day(conn, where, params),
    }


async def _summary_totals(conn: aiosqlite.Connection, where: str, params: list) -> dict:
    """The totals block: sums, the error and cache-hit rates, priced/unpriced split."""
    cursor = await conn.execute(f"""
        SELECT COUNT(*) AS requests,
               COALESCE(SUM(CASE WHEN {_ERR_SQL} THEN 1 ELSE 0 END), 0) AS errors,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               SUM(cost_usd) AS cost_usd,
               COALESCE(SUM(CASE WHEN cost_usd IS NULL AND prompt_tokens + completion_tokens > 0
                                 THEN 1 ELSE 0 END), 0) AS unpriced
        FROM usage_events {where}
    """, params)
    row = await cursor.fetchone()
    requests, errors = row["requests"], row["errors"]
    prompt, cached = row["prompt_tokens"], row["cached_tokens"]
    return {
        "requests": requests,
        "errors": errors,
        "error_rate": (errors / requests) if requests else 0.0,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "completion_tokens": row["completion_tokens"],
        "reasoning_tokens": row["reasoning_tokens"],
        "total_tokens": row["total_tokens"],
        "cost_usd": row["cost_usd"],
        "unpriced": row["unpriced"],
        "cache_hit_rate": (cached / prompt) if prompt else 0.0,
    }


async def _breakdown(conn: aiosqlite.Connection, where: str, params: list,
                     dimension: str, label: str) -> list[dict]:
    """Per-dimension sums (user / model / provider), heaviest token user first."""
    cursor = await conn.execute(f"""
        SELECT {dimension} AS "{label}",
               COUNT(*) AS requests,
               COALESCE(SUM(CASE WHEN {_ERR_SQL} THEN 1 ELSE 0 END), 0) AS errors,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               SUM(cost_usd) AS cost_usd
        FROM usage_events {where}
        GROUP BY {dimension}
        ORDER BY SUM(usage_events.total_tokens) DESC
    """, params)
    return [dict(row) for row in await cursor.fetchall()]


async def _by_error_code(conn: aiosqlite.Connection, where: str, params: list) -> list[dict]:
    """Errors only (NULL error_code bucket = errors that bypassed the
    enrichment point: 422s, disconnects, string-detail 404s)."""
    cursor = await conn.execute(f"""
        SELECT error_code, COUNT(*) AS count
        FROM usage_events {where}{' AND ' + _ERR_SQL if where else ' WHERE ' + _ERR_SQL}
        GROUP BY error_code
        ORDER BY COUNT(*) DESC
    """, params)
    return [dict(row) for row in await cursor.fetchall()]


async def _by_day(conn: aiosqlite.Connection, where: str, params: list) -> list[dict]:
    """Per-UTC-day sums, oldest first."""
    cursor = await conn.execute(f"""
        SELECT date(timestamp, 'unixepoch') AS day,
               COUNT(*) AS requests,
               COALESCE(SUM(CASE WHEN {_ERR_SQL} THEN 1 ELSE 0 END), 0) AS errors,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               SUM(cost_usd) AS cost_usd
        FROM usage_events {where}
        GROUP BY day
        ORDER BY day
    """, params)
    return [dict(row) for row in await cursor.fetchall()]


def _request_filters(
    providers: list[str], status: str, error_code: str, request_id: str,
) -> tuple[list[str], list]:
    """Conditions specific to the request log (status, error code, id, providers)."""
    conditions: list[str] = []
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
    return conditions, params


async def get_requests(
    users: list[str],
    models: list[str],
    providers: list[str],
    status: str,
    error_code: str,
    request_id: str,
    days: int | None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Newest-first request log with filters and pagination."""
    conn = get_connection()
    if conn is None:
        return {"requests": [], "total": 0}

    conditions, params = _request_filters(providers, status, error_code, request_id)
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
    return {
        "requests": [{**dict(row), "stream": bool(row["stream"])}
                     for row in await cursor.fetchall()],
        "total": total,
    }
