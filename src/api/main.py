"""FastAPI application, lifespan management, and route definitions."""
# SYSTEM: api-app — FastAPI app, lifespan, routes, eager provider validation
import asyncio
import contextlib
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..core.auth import check_endpoint_access
from ..core.config_manager import ConfigManager
from ..core.context import AuthContext, request_context
from ..core.error_handling import ErrorType, create_error, enrich_stats_from_envelope
from ..core.logging import logger
from ..core.model_capabilities import CapabilitiesCache, capabilities_refresh_loop
from ..core.usage_db import close_db, drain_pending_flushes, init_db, request_stats
from ..providers import (
    clear_provider_cache_async,
    prepare_provider_cache,
    publish_provider_cache,
)
from ..services.chat_service.chat_service import ChatService
from ..services.embedding_service import EmbeddingService
from ..services.model_service import ModelService
from ..services.transcription_service import TranscriptionService
from ..utils.client_address import client_host
from ..utils.generate_key import generate_key
from .middleware import RequestLoggerMiddleware
from .stat_page import STATIC_DIR, stat_page
from .stat_routes import router as stat_router


async def _validate_providers(config_manager: ConfigManager) -> None:
    """Eager validation: build & cache every configured provider (fail-fast).

    prepare + publish back to back — the same pair a config reload drives in
    its two phases. All failures are collected by prepare_provider_cache into
    one RuntimeError so operators can fix multiple issues at once.
    """
    await prepare_provider_cache(config_manager.get_config(), config_manager.settings)
    await publish_provider_cache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ConfigManager, validate providers, and all services; tear down on shutdown."""
    config_manager = ConfigManager()
    app.state.config_manager = config_manager

    # ARCH: eager validation — fail fast on bad provider config / missing env keys.
    await _validate_providers(config_manager)

    # ARCH: two-phase provider-cache reload. prepare runs pre-swap (it can
    # veto a broken providers.yaml by raising); publish runs post-swap, after
    # self.config is already the new one, so a provider removed by the reload
    # cannot be re-populated from the stale config (see the INVARIANT on
    # publish_provider_cache).
    async def _prepare_on_reload(new_config: dict) -> None:
        """Pre-swap callback: stage the provider cache for the freshly loaded config."""
        await prepare_provider_cache(new_config, config_manager.settings)

    async def _publish_on_reload(new_config: dict) -> None:
        """Post-swap callback: publish the staged cache, drain superseded pools."""
        await publish_provider_cache()

    config_manager.add_reload_callback(_prepare_on_reload, name="prepare_provider_cache")
    config_manager.add_post_swap_callback(_publish_on_reload, name="publish_provider_cache")
    reload_task = config_manager.start_reloader_task()

    # ARCH: capabilities auto-cache. Loaded from disk so data is available even
    # when upstreams are down; refreshed in the background (never blocks startup,
    # never touches the network on the hot path).
    capabilities_cache = CapabilitiesCache(config_manager.settings.model_cache_path)
    capabilities_cache.load()

    app.state.model_service = ModelService(config_manager, capabilities_cache)
    app.state.chat_service = ChatService(config_manager, app.state.model_service)
    app.state.embedding_service = EmbeddingService(config_manager)
    app.state.transcription_service = TranscriptionService(config_manager, app.state.model_service)

    await init_db(config_manager.settings.usage_db_path)

    capabilities_task = asyncio.create_task(capabilities_refresh_loop(config_manager, capabilities_cache))

    yield

    reload_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reload_task
    capabilities_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await capabilities_task
    # Close every provider-owned pool on shutdown (awaited so pools drain),
    # then drain pending usage flushes BEFORE the DB connection closes — an
    # in-flight _flush_row would otherwise race close_db() and silently no-op.
    await clear_provider_cache_async()
    await drain_pending_flushes()
    await close_db()

app = FastAPI(lifespan=lifespan)
app.mount("/stat/static", StaticFiles(directory=STATIC_DIR), name="stat_static")
app.include_router(stat_router)

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """OpenRouter-compatible error shape + the single error-enrichment point.

    Writes error_code / error_message / provider_name into the per-request
    stats holder out of exc.detail (best-effort) via the ONE envelope
    extractor (core/error_handling/envelope.py), shared with the stream
    processor's mid-stream error path so the two cannot drift. Enrichment
    tolerates details without metadata.error_code: a plain string detail
    (unmatched-route 404s) writes only error_message and leaves error_code
    NULL — an error status with NULL error_code is an expected shape, the UI
    groups it under "—".
    """
    stats = request_stats(request)
    content = exc.detail
    if isinstance(content, dict) and "error" in content:
        enrich_stats_from_envelope(stats, content)
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

@app.get("/v1/models", name="models")
async def list_models(
    auth_context: AuthContext = Depends(check_endpoint_access("/v1/models"))
):
    return await app.state.model_service.list_models(auth_context)


# ARCH: the endpoint string "/v1/models/{model_id:path}" differs from "/v1/models" —
# this is what allows granting access to the model list without access to a
# specific model's detail endpoint
@app.get("/v1/models/{model_id:path}", name="models")
async def retrieve_model(
    model_id: str,
    refresh: bool = False,
    auth_context: AuthContext = Depends(check_endpoint_access("/v1/models/{model_id:path}"))
):
    return await app.state.model_service.retrieve_model(model_id, auth_context, refresh=refresh)

@app.post("/v1/chat/completions", name="chat")
async def chat_completions(
    request: Request,
    auth_context: AuthContext = Depends(check_endpoint_access("/v1/chat/completions"))
):
    return await app.state.chat_service.chat_completions(request, auth_context)

@app.post("/v1/embeddings", name="embeddings")
async def create_embeddings(
    request: Request,
    auth_context: AuthContext = Depends(check_endpoint_access("/v1/embeddings"))
):
    return await app.state.embedding_service.create_embeddings(request, auth_context)

@app.post("/v1/audio/transcriptions", name="transcriptions")
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
    auth_context: AuthContext = Depends(check_endpoint_access("/v1/audio/transcriptions"))
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
        auth_context=auth_context,
        model_id=model,
        response_format=response_format,
        temperature=temperature,
        language=language,
        return_timestamps=return_timestamps,
    )

@app.get("/tools/generate_key", name="generate_key")
async def generate_key_endpoint(
    request: Request,
    auth_context: AuthContext = Depends(check_endpoint_access("/tools/generate_key"))
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


@app.get("/stat/")
async def stat_dashboard(request: Request):
    # The page stays open even with STAT_API_KEY set: it is what prompts for
    # the key. /stat/static is a mount and cannot carry a dependency at all.
    # The /stat/api/* JSON endpoints live in stat_routes.py (stat_router).
    return await stat_page(request)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
