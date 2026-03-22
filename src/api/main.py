"""FastAPI application, lifespan management, and route definitions."""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status, Depends, File, Form, UploadFile
from typing import Optional
import uvicorn
import httpx
from typing import Dict, Any

from ..core.config_manager import ConfigManager
from ..core.auth import get_api_key, check_endpoint_access
from ..core.error_handling import ErrorType, create_error
from ..services.chat_service.chat_service import ChatService
from ..services.model_service import ModelService
from ..services.embedding_service import EmbeddingService
from ..services.transcription_service import TranscriptionService
from ..core.logging import logger
from ..utils.generate_key import generate_key
from ..providers import clear_provider_cache
from .middleware import RequestLoggerMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ConfigManager, httpx pool, and all services; tear down on shutdown."""
    config_manager = ConfigManager()
    app.state.config_manager = config_manager
    config_manager.add_reload_callback(clear_provider_cache)
    reload_task = config_manager.start_reloader_task()

    limits = httpx.Limits(
        max_connections=config_manager.httpx_max_connections,
        max_keepalive_connections=config_manager.httpx_max_keepalive_connections
    )
    app.state.httpx_client = httpx.AsyncClient(
        limits=limits,
        timeout=httpx.Timeout(
            connect=config_manager.httpx_connect_timeout,
            read=config_manager.httpx_read_timeout,
            write=None,
            pool=config_manager.httpx_pool_timeout
        )
    )

    app.state.model_service = ModelService(config_manager, app.state.httpx_client)
    app.state.chat_service = ChatService(config_manager, app.state.httpx_client, app.state.model_service)
    app.state.embedding_service = EmbeddingService(config_manager, app.state.httpx_client)
    app.state.transcription_service = TranscriptionService(config_manager, app.state.httpx_client, app.state.model_service)

    yield

    reload_task.cancel()
    try:
        await reload_task
    except asyncio.CancelledError:
        pass
    await app.state.httpx_client.aclose()

app = FastAPI(lifespan=lifespan)

from fastapi.responses import JSONResponse

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
    request_id = getattr(request.state, 'request_id', 'unknown')
    user_id = getattr(request.state, 'project_name', 'unknown')

    logger.info(
        f"Request: Transcription | model={model}",
        request_id=request_id,
        user_id=user_id,
        method=request.method,
        url=str(request.url),
        client_host=request.client.host,
        model=model,
        response_format=response_format,
        temperature=temperature,
        language=language,
        return_timestamps=return_timestamps
    )

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
        extra={
            "log_type": "request",
            "request_id": request_id,
            "user_id": user_id,
            "file_details": {
                "filename": uploaded_file.filename,
                "content_type": uploaded_file.content_type,
                "size": uploaded_file.size if hasattr(uploaded_file, 'size') else 'unknown'
            }
        }
    )

    return await app.state.transcription_service.create_transcription(
        uploaded_file, model, auth_data, response_format, temperature, language, return_timestamps
    )

@app.get("/tools/generate_key")
async def generate_key_endpoint(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/tools/generate_key"))
):
    request_id = getattr(request.state, 'request_id', 'unknown')
    user_id = getattr(request.state, 'project_name', 'unknown')

    logger.info(
        "Key generation request received",
        extra={
            "log_type": "request",
            "request_id": request_id,
            "user_id": user_id,
            "method": request.method,
            "url": str(request.url),
            "client_host": request.client.host
        }
    )

    key = generate_key()
    logger.debug_data(
        title="Generated API Key",
        data={"key": key},
        request_id=request_id
    )
    return {"key": key}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
