"""FastAPI application, lifespan management, and route definitions."""
# SYSTEM: api-app — FastAPI app, lifespan, routes, eager provider validation
import asyncio
import contextlib
import hmac
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..core.auth import check_endpoint_access
from ..core.config_manager import ConfigManager
from ..core.context import request_context
from ..core.error_handling import ErrorType, create_error
from ..core.logging import logger
from ..core.model_capabilities import CapabilitiesCache, capabilities_refresh_loop
from ..core.usage_db import (
    close_db,
    get_distinct_models,
    get_distinct_users,
    get_requests,
    get_summary,
    get_usage_data,
    init_db,
    request_stats,
)
from ..providers import clear_provider_cache_async, rebuild_provider_cache
from ..services.chat_service.chat_service import ChatService
from ..services.embedding_service import EmbeddingService
from ..services.model_service import ModelService
from ..services.transcription_service import TranscriptionService
from ..utils.client_address import client_host
from ..utils.generate_key import generate_key
from .middleware import RequestLoggerMiddleware
from .stat_page import STATIC_DIR, stat_page


async def _validate_providers(config_manager: ConfigManager) -> None:
    """Eager validation: build & cache every configured provider (fail-fast).

    All failures are collected by rebuild_provider_cache into one RuntimeError so
    operators can fix multiple issues at once.
    """
    await rebuild_provider_cache(config_manager.get_config(), config_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ConfigManager, validate providers, and all services; tear down on shutdown."""
    config_manager = ConfigManager()
    app.state.config_manager = config_manager

    # ARCH: eager validation — fail fast on bad provider config / missing env keys.
    await _validate_providers(config_manager)

    async def _rebuild_on_reload(new_config: dict) -> None:
        """Reload callback: rebuild the provider cache for the freshly loaded config."""
        await rebuild_provider_cache(new_config, config_manager)

    config_manager.add_reload_callback(_rebuild_on_reload, name="rebuild_provider_cache")
    reload_task = config_manager.start_reloader_task()

    # ARCH: capabilities auto-cache. Loaded from disk so data is available even
    # when upstreams are down; refreshed in the background (never blocks startup,
    # never touches the network on the hot path).
    capabilities_cache = CapabilitiesCache(config_manager.model_cache_path)
    capabilities_cache.load()

    app.state.model_service = ModelService(config_manager, capabilities_cache)
    app.state.chat_service = ChatService(config_manager, app.state.model_service)
    app.state.embedding_service = EmbeddingService(config_manager)
    app.state.transcription_service = TranscriptionService(config_manager, app.state.model_service)

    await init_db(config_manager.usage_db_path)

    capabilities_task = asyncio.create_task(capabilities_refresh_loop(config_manager, capabilities_cache))

    yield

    reload_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reload_task
    capabilities_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await capabilities_task
    # Close every provider-owned pool on shutdown (awaited so pools drain).
    await clear_provider_cache_async()
    await close_db()

app = FastAPI(lifespan=lifespan)
app.mount("/stat/static", StaticFiles(directory=STATIC_DIR), name="stat_static")

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """OpenRouter-compatible error shape + the single error-enrichment point.

    Writes error_code / error_message / provider_name into the per-request
    stats holder out of exc.detail (best-effort). Enrichment tolerates details
    without metadata.error_code: a plain string detail (unmatched-route 404s)
    writes only error_message and leaves error_code NULL — an error status
    with NULL error_code is an expected shape, the UI groups it under "—".
    """
    stats = request_stats(request)
    content = exc.detail
    if isinstance(content, dict) and "error" in content:
        error = content["error"]
        message = error.get("message")
        if message:
            stats.error_message = str(message)
        metadata = error.get("metadata")
        if isinstance(metadata, dict):
            error_code = metadata.get("error_code")
            if error_code:
                stats.error_code = str(error_code)
            provider_name = metadata.get("provider_name")
            if provider_name and not stats.provider_name:
                stats.provider_name = str(provider_name)
        return JSONResponse(status_code=exc.status_code, content=content)
    if content is not None:
        stats.error_message = str(content)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": str(content)}}
    )

app.add_middleware(RequestLoggerMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """OpenRouter envelope for unhandled exceptions (ServerErrorMiddleware's layer).

    Starlette re-raises after this handler responds (uvicorn still logs the
    traceback), so the response is sent exactly once. Usage-stats flushing is
    unaffected: RequestLoggerMiddleware sits BELOW ServerErrorMiddleware, so
    its ``finally`` still records the row as a 500. The message is generic on
    purpose — the traceback lives in the server log, not the client response.
    No exc_info here on purpose: RequestLoggerMiddleware below already logs
    the full traceback with the request_id, and uvicorn logs the re-raise.
    """
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {exc}",
        request_id=request_context(request).request_id,
    )
    return JSONResponse(
        status_code=500,
        content={"error": {"code": 500,
                           "message": "Internal server error",
                           "metadata": {"error_code": "internal_server_error"}}},
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/v1/models")
async def list_models(
    auth_data: tuple = Depends(check_endpoint_access("/v1/models"))
):
    return await app.state.model_service.list_models(auth_data)


# ARCH: endpoint string "/v1/models/{model_id:path}" отличается от "/v1/models" —
# это позволяет давать доступ к списку моделей без доступа к деталям конкретной модели
@app.get("/v1/models/{model_id:path}")
async def retrieve_model(
    model_id: str,
    refresh: bool = False,
    auth_data: tuple = Depends(check_endpoint_access("/v1/models/{model_id:path}"))
):
    return await app.state.model_service.retrieve_model(model_id, auth_data, refresh=refresh)

@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/v1/chat/completions"))
):
    return await app.state.chat_service.chat_completions(request, auth_data)

@app.post("/v1/embeddings")
async def create_embeddings(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/v1/embeddings"))
):
    return await app.state.embedding_service.create_embeddings(request, auth_data)

@app.post("/v1/audio/transcriptions")
async def create_transcription(
    request: Request,
    # WHY: some clients send 'audio_file', others 'file' — accept both
    audio_file: UploadFile | None = File(None),
    file: UploadFile | None = File(None),
    model: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
    language: str | None = Form(None),
    return_timestamps: bool | None = Form(False),
    auth_data: tuple = Depends(check_endpoint_access("/v1/audio/transcriptions"))
):
    ctx = request_context(request)
    request_id = ctx.request_id
    user_id = ctx.user_id

    logger.debug_data(
        title="Transcription Request Headers",
        data=dict(request.headers),
        request_id=request_id,
        component="api",
        data_flow="incoming"
    )

    if audio_file:
        uploaded_file = audio_file
    elif file:
        uploaded_file = file
    else:
        raise create_error(ErrorType.MISSING_REQUIRED_FIELD, field_name="audio_file or file")

    logger.info(
        "Transcription file received",
        request_id=request_id,
        user_id=user_id,
        file_details={
            "filename": uploaded_file.filename,
            "content_type": uploaded_file.content_type,
            "size": uploaded_file.size if hasattr(uploaded_file, 'size') else 'unknown'
        }
    )

    return await app.state.transcription_service.create_transcription(
        request=request,
        audio_file=uploaded_file,
        auth_data=auth_data,
        model_id=model,
        response_format=response_format,
        temperature=temperature,
        language=language,
        return_timestamps=return_timestamps,
    )

@app.get("/tools/generate_key")
async def generate_key_endpoint(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/tools/generate_key"))
):
    ctx = request_context(request)
    request_id = ctx.request_id
    user_id = ctx.user_id

    logger.info(
        "Key generation request received",
        request_id=request_id,
        user_id=user_id,
        method=request.method,
        url=str(request.url),
        client_host=client_host(request)
    )

    key = generate_key()
    logger.debug_data(
        title="Generated API Key",
        data={"key": f"{key[:10]}..."},
        request_id=request_id
    )
    return {"key": key}


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
    expected = getattr(config_manager, "stat_api_key", "") or ""
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


@app.get("/stat/")
async def stat_dashboard(request: Request):
    # The page stays open even with STAT_API_KEY set: it is what prompts for
    # the key. /stat/static is a mount and cannot carry a dependency at all.
    return await stat_page(request)


@app.get("/stat/api/users")
async def stat_users(_: None = Depends(verify_stat_key)):
    return await get_distinct_users()


@app.get("/stat/api/models")
async def stat_models(_: None = Depends(verify_stat_key)):
    return await get_distinct_models()


@app.get("/stat/api/usage")
async def stat_usage(
    users: str = "",
    models: str = "",
    days: str = "",
    _: None = Depends(verify_stat_key),
):
    user_list = [u.strip() for u in users.split(",") if u.strip()] if users else []
    model_list = [m.strip() for m in models.split(",") if m.strip()] if models else []
    days_int = _parse_days_param(days)
    return await get_usage_data(user_list, model_list, days_int)


@app.get("/stat/api/summary")
async def stat_summary(
    users: str = "",
    models: str = "",
    days: str = "",
    _: None = Depends(verify_stat_key),
):
    user_list = [u.strip() for u in users.split(",") if u.strip()] if users else []
    model_list = [m.strip() for m in models.split(",") if m.strip()] if models else []
    days_int = _parse_days_param(days)
    return await get_summary(user_list, model_list, days_int)


@app.get("/stat/api/requests")
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
    user_list = [u.strip() for u in users.split(",") if u.strip()] if users else []
    model_list = [m.strip() for m in models.split(",") if m.strip()] if models else []
    provider_list = [p.strip() for p in providers.split(",") if p.strip()] if providers else []
    days_int = _parse_days_param(days)
    return await get_requests(
        user_list, model_list, provider_list, status, error_code,
        request_id, days_int, limit=limit, offset=offset,
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
