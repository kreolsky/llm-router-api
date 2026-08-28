"""Dashboard query side of usage tracking: every read path for /stat/api/*.

Pure reads over usage_events; shares only the connection (in _conn.py) with
the writer. No SQL beyond what the module held before the split.
"""

import time

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
        # strict=True: dates and the metric triples are appended together row by
        # row, so unequal lengths would mean corrupted series data — fail loudly.
        date_map = dict(zip(s["dates"],
                            zip(s["prompt"], s["cached"], s["completion"], strict=True),
                            strict=True))
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

    async def _breakdown(dimension: str, label: str) -> list[dict]:
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
