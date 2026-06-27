"""SQLite-backed token usage tracking for the /stat/ dashboard."""

import os
import time
import aiosqlite

DB_PATH = os.environ.get("USAGE_DB_PATH", "data/usage.db")

_connection: aiosqlite.Connection | None = None


async def init_db() -> None:
    global _connection
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    _connection = await aiosqlite.connect(DB_PATH)
    await _connection.execute("PRAGMA journal_mode=WAL")
    await _connection.execute("""
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
        )
    """)
    await _connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_usage_project_model_ts
        ON usage_events(project_name, model_id, timestamp)
    """)
    await _connection.commit()


async def close_db() -> None:
    global _connection
    if _connection:
        await _connection.close()
        _connection = None


def get_connection() -> aiosqlite.Connection:
    return _connection


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
    status_code: int = 200,
) -> None:
    try:
        conn = get_connection()
        if conn is None:
            return
        await conn.execute(
            """INSERT INTO usage_events
               (request_id, project_name, model_id, provider_name, endpoint,
                timestamp, prompt_tokens, completion_tokens, cached_tokens,
                total_tokens, duration_ms, status_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id,
                project_name,
                model_id,
                provider_name,
                endpoint,
                time.time(),
                prompt_tokens,
                completion_tokens,
                cached_tokens,
                total_tokens,
                duration_ms,
                status_code,
            ),
        )
        await conn.commit()
    except Exception:
        pass


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

    conditions = []
    params: list = []

    if users:
        placeholders = ",".join("?" for _ in users)
        conditions.append(f"project_name IN ({placeholders})")
        params.extend(users)

    if models:
        placeholders = ",".join("?" for _ in models)
        conditions.append(f"model_id IN ({placeholders})")
        params.extend(models)

    if days is not None:
        cutoff = time.time() - days * 86400
        conditions.append("timestamp >= ?")
        params.append(cutoff)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

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
