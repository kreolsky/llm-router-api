from fastapi import FastAPI, Request, HTTPException, status, Depends
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn
import asyncio
import os
import time
import logging
import json
from typing import Dict, Any

from ..core.config_manager import ConfigManager
from ..core.auth import get_api_key
from ..providers import get_provider_instance
from ..services.chat_service import ChatService
from ..services.model_service import ModelService
from ..services.embedding_service import EmbeddingService # Import EmbeddingService
from ..logging.config import setup_logging # Import setup_logging
from .middleware import RequestLoggerMiddleware # Import RequestLoggerMiddleware

# Configure logging
setup_logging()

logger = logging.getLogger("nnp-llm-router")

app = FastAPI()

# Initialize ConfigManager
config_manager = ConfigManager()
app.state.config_manager = config_manager

import httpx # Add httpx import

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

@app.on_event("shutdown")
async def shutdown_event():
    # Close httpx client
    await app.state.httpx_client.aclose()

app.add_middleware(RequestLoggerMiddleware)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/v1/models")
async def list_models():
    return await app.state.model_service.list_models()


@app.get("/v1/models/{model_id:path}")
async def retrieve_model(model_id: str):
    return await app.state.model_service.retrieve_model(model_id)

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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
