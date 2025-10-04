from fastapi import FastAPI, Request, HTTPException, status, Depends, File, Form, UploadFile
from typing import Optional
import uvicorn
import logging
import httpx
from typing import Dict, Any

from ..core.config_manager import ConfigManager
from ..core.auth import get_api_key
from ..services.chat_service.chat_service import ChatService
from ..services.model_service import ModelService
from ..services.embedding_service import EmbeddingService
from ..services.transcription_service import TranscriptionService
from ..logging.config import setup_logging
from .middleware import RequestLoggerMiddleware

# Configure logging
setup_logging()

logger = logging.getLogger("nnp-llm-router")

app = FastAPI()

# Initialize ConfigManager
config_manager = ConfigManager()
app.state.config_manager = config_manager

@app.on_event("startup")
async def startup_event():
    # Start config reloader task
    app.state.config_manager.start_reloader_task()
    
    # Initialize httpx client
    app.state.httpx_client = httpx.AsyncClient()

    # Initialize ModelService
    app.state.model_service = ModelService(app.state.config_manager, app.state.httpx_client)

    # Initialize ChatService
    app.state.chat_service = ChatService(app.state.config_manager, app.state.httpx_client, app.state.model_service)

    # Initialize EmbeddingService
    app.state.embedding_service = EmbeddingService(app.state.config_manager, app.state.httpx_client)

    # Initialize TranscriptionService
    app.state.transcription_service = TranscriptionService(app.state.config_manager, app.state.httpx_client, app.state.model_service)

@app.on_event("shutdown")
async def shutdown_event():
    # Close httpx client
    await app.state.httpx_client.aclose()

app.add_middleware(RequestLoggerMiddleware)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/v1/models")
async def list_models(
    auth_data: tuple = Depends(get_api_key)
):
    return await app.state.model_service.list_models(auth_data)


@app.get("/v1/models/{model_id:path}")
async def retrieve_model(model_id: str, auth_data: tuple = Depends(get_api_key)):
    return await app.state.model_service.retrieve_model(model_id, auth_data)

@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    auth_data: tuple = Depends(get_api_key)
):
    return await app.state.chat_service.chat_completions(request, auth_data)

@app.post("/v1/embeddings")
async def create_embeddings(
    request: Request,
    auth_data: tuple = Depends(get_api_key)
):
    return await app.state.embedding_service.create_embeddings(request, auth_data)

@app.post("/v1/audio/transcriptions")
async def create_transcription(
    request: Request, # Add Request to access headers
    audio_file: Optional[UploadFile] = File(None), # Make audio_file optional
    file: Optional[UploadFile] = File(None), # Add 'file' as an optional parameter
    model: str = Form(...),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
    language: Optional[str] = Form(None),
    return_timestamps: Optional[bool] = Form(False), # Add return_timestamps
    auth_data: tuple = Depends(get_api_key)
):
    logger.info(f"Transcription request received from {request.client.host}")
    logger.info(f"Request Headers: {dict(request.headers)}")
    logger.info(f"Form Fields: model={model}, response_format={response_format}, temperature={temperature}, language={language}, return_timestamps={return_timestamps}") # Log return_timestamps
    # Determine which file was provided
    if audio_file:
        uploaded_file = audio_file
    elif file:
        uploaded_file = file
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"message": "No audio file provided. Please upload 'audio_file' or 'file'.", "code": "no_audio_file"}}
        )

    logger.info(f"Audio File: filename={uploaded_file.filename}, content_type={uploaded_file.content_type}, size={uploaded_file.size if hasattr(uploaded_file, 'size') else 'unknown'}")
    return await app.state.transcription_service.create_transcription(
        uploaded_file, model, auth_data, response_format, temperature, language, return_timestamps
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
