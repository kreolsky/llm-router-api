"""APIRouter carrying the /stat/api/* JSON endpoints of the usage dashboard.

The dashboard HTML page itself lives in stat_page.py (see SYSTEM:
stat-dashboard); this router owns only the JSON read paths over
usage_events. Mounted from api/main.py via app.include_router.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..core.usage_db import (
    get_distinct_models,
    get_distinct_users,
    get_requests,
    get_summary,
    get_usage_data,
)

router = APIRouter()


async def verify_stat_key(
    request: Request,
    x_stat_key: str | None = Header(None, alias="X-Stat-Key"),
) -> None:
    """Require X-Stat-Key on /stat/api/* when STAT_API_KEY is configured.

    WHY header only, never a ?stat_key= query param: the logging middleware
    logs the full URL including the query string, so a query-param key would
    leak into request logs. When STAT_API_KEY is unset everything stays open.
    """
    config_manager = getattr(request.app.state, "config_manager", None)
    settings = getattr(config_manager, "settings", None) if config_manager is not None else None
    expected = settings.stat_api_key if settings is not None else ""
    if expected and not hmac.compare_digest(
            (x_stat_key or "").encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": 401,
                              "message": "Invalid or missing X-Stat-Key header"}},
        )


def _parse_days_param(days: str) -> int | None:
    """Parse the `days` query param shared by the /stat/api endpoints.

    WHY kept a string: the dashboard's "All" button sends an EMPTY value
    (stat.html), which must mean "no day filter" — a bare `days: int | None`
    would 422 that button. Non-numeric input answers 422 in the OpenRouter
    envelope instead of a ValueError-driven 500.
    """
    if not days or not days.strip():
        return None
    try:
        return int(days)
    except ValueError:
        # from None: the ValueError is the client's own bad input — nothing
        # to chain for the server log.
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": 422,
                              "message": f"Query parameter 'days' must be an integer, got {days!r}",
                              "metadata": {}}},
        ) from None


def _csv_list(raw: str) -> list[str]:
    """Split a comma-separated filter param into stripped non-empty items."""
    return [item.strip() for item in raw.split(",") if item.strip()]


@router.get("/stat/api/users")
async def stat_users(_: None = Depends(verify_stat_key)):
    return await get_distinct_users()


@router.get("/stat/api/models")
async def stat_models(_: None = Depends(verify_stat_key)):
    return await get_distinct_models()


@router.get("/stat/api/usage")
async def stat_usage(
    users: str = "",
    models: str = "",
    days: str = "",
    _: None = Depends(verify_stat_key),
):
    days_int = _parse_days_param(days)
    return await get_usage_data(_csv_list(users), _csv_list(models), days_int)


@router.get("/stat/api/summary")
async def stat_summary(
    users: str = "",
    models: str = "",
    days: str = "",
    _: None = Depends(verify_stat_key),
):
    days_int = _parse_days_param(days)
    return await get_summary(_csv_list(users), _csv_list(models), days_int)


@router.get("/stat/api/requests")
async def stat_requests(
    users: str = "",
    models: str = "",
    providers: str = "",
    status: str = "all",
    error_code: str = "",
    request_id: str = "",
    days: str = "",
    limit: int = 50,
    offset: int = 0,
    _: None = Depends(verify_stat_key),
):
    days_int = _parse_days_param(days)
    return await get_requests(
        _csv_list(users), _csv_list(models), _csv_list(providers), status, error_code,
        request_id, days_int, limit=limit, offset=offset,
    )
