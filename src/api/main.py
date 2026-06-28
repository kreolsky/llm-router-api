"""FastAPI application, lifespan management, and route definitions."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status, Depends, File, Form, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from typing import Optional
import uvicorn
from typing import Dict, Any

from ..core.config_manager import ConfigManager
from ..core.auth import get_api_key, check_endpoint_access
from ..core.context import RequestContext
from ..core.error_handling import ErrorType, create_error
from ..services.chat_service.chat_service import ChatService
from ..services.model_service import ModelService
from ..services.embedding_service import EmbeddingService
from ..services.transcription_service import TranscriptionService
from ..core.logging import logger
from ..utils.generate_key import generate_key
from ..providers import clear_provider_cache_async, rebuild_provider_cache
from .middleware import RequestLoggerMiddleware


def _client_host(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# Strong references for in-flight reload-rebuild tasks (prevents GC before completion).
_reload_tasks: set[asyncio.Task] = set()


def _request_context(request: Request) -> RequestContext:
    """Read the typed RequestContext set by middleware/auth."""
    return getattr(request.state, "request_context", None) or RequestContext(request_id="unknown")


async def _validate_providers(config_manager: ConfigManager) -> None:
    """Eager validation: build & cache every configured provider (fail-fast).

    All failures are collected by rebuild_provider_cache into one RuntimeError so
    operators can fix multiple issues at once.
    """
    await rebuild_provider_cache(config_manager.get_config(), config_manager)


def _make_reload_callback(config_manager: ConfigManager):
    """Build a reload callback that atomically rebuilds the provider cache.

    Exceptions are caught + logged so a single bad reload never crashes the
    background reload task; the previous cache is retained on failure. The
    scheduled rebuild task is kept alive in a module-level set so it is not
    garbage-collected before completion.
    """
    def _on_reload_done(task: asyncio.Task) -> None:
        _reload_tasks.discard(task)

    def _rebuild_on_reload() -> None:
        async def _do_rebuild():
            try:
                await rebuild_provider_cache(config_manager.get_config(), config_manager)
            except Exception as e:
                logger.error(
                    f"Provider cache rebuild failed on config reload; previous cache retained: {e}",
                    extra={
                        "log_type": "error",
                        "error_type": "provider_cache_rebuild_error",
                        "error_message": str(e),
                    },
                    exc_info=True,
                )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            task = loop.create_task(_do_rebuild())
            _reload_tasks.add(task)
            task.add_done_callback(_on_reload_done)
        else:
            asyncio.run(_do_rebuild())
    return _rebuild_on_reload


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ConfigManager, validate providers, and all services; tear down on shutdown."""
    config_manager = ConfigManager()
    app.state.config_manager = config_manager

    # ARCH: eager validation — fail fast on bad provider config / missing env keys.
    await _validate_providers(config_manager)

    config_manager.add_reload_callback(_make_reload_callback(config_manager))
    reload_task = config_manager.start_reloader_task()

    app.state.model_service = ModelService(config_manager)
    app.state.chat_service = ChatService(config_manager, app.state.model_service)
    app.state.embedding_service = EmbeddingService(config_manager)
    app.state.transcription_service = TranscriptionService(config_manager, app.state.model_service)

    from ..core.usage_db import init_db, close_db
    await init_db()

    yield

    reload_task.cancel()
    try:
        await reload_task
    except asyncio.CancelledError:
        pass
    # Close every provider-owned pool on shutdown (awaited so pools drain).
    await clear_provider_cache_async()
    await close_db()

app = FastAPI(lifespan=lifespan)
app.mount("/stat/static", StaticFiles(directory="src/static"), name="stat_static")

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    # WHY: FastAPI wraps detail in {"detail": ...} by default; we return error dict directly for OpenRouter compatibility
    content = exc.detail
    if isinstance(content, dict) and "error" in content:
        return JSONResponse(status_code=exc.status_code, content=content)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": str(content)}}
    )

app.add_middleware(RequestLoggerMiddleware)

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
async def retrieve_model(model_id: str, auth_data: tuple = Depends(check_endpoint_access("/v1/models/{model_id:path}"))):
    return await app.state.model_service.retrieve_model(model_id, auth_data)

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
    audio_file: Optional[UploadFile] = File(None),
    file: Optional[UploadFile] = File(None),
    model: Optional[str] = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
    language: Optional[str] = Form(None),
    return_timestamps: Optional[bool] = Form(False),
    auth_data: tuple = Depends(check_endpoint_access("/v1/audio/transcriptions"))
):
    ctx = _request_context(request)
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
    ctx = _request_context(request)
    request_id = ctx.request_id
    user_id = ctx.user_id

    logger.info(
        "Key generation request received",
        request_id=request_id,
        user_id=user_id,
        method=request.method,
        url=str(request.url),
        client_host=_client_host(request)
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
