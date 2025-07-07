import httpx
import json
import time
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from .model_service import ModelService
from ..logging.config import logger

class ChatService:
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.httpx_client = httpx_client
        self.model_service = model_service

    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list]) -> Any:
        project_name, api_key, allowed_models = auth_data
        request_id = request.state.request_id
        user_id = project_name

        request_body = await request.json()
        requested_model = request_body.get("model")

        self._log_chat_completion_request(request_id, user_id, requested_model, request_body)

        model_config, provider_name, provider_model_name, provider_config = \
            self._validate_request_and_model(requested_model, allowed_models, api_key, project_name, request_id, user_id)

        provider_instance = self._get_provider_instance(provider_config, request_id, user_id)
        
        try:
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            if isinstance(response_data, StreamingResponse):
                return StreamingResponse(self._stream_response_handler(response_data, provider_config.get("type"), requested_model, request_id, user_id), media_type=response_data.media_type)
            else:
                self._log_non_streaming_response(request_id, user_id, requested_model, response_data)
                return JSONResponse(content=response_data)
            
        except HTTPException as e:
            self._log_http_exception(e, request_id, user_id, requested_model)
            raise e
        except Exception as e:
            self._log_unexpected_exception(e, request_id, user_id, requested_model)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}},
            )

    def _log_chat_completion_request(self, request_id: str, user_id: str, requested_model: str, request_body: Dict[str, Any]):
        logger.info(
            "Chat Completion Request",
            extra={
                "log_type": "request",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "request_body_summary": {
                    "model": requested_model,
                    "messages_count": len(request_body.get("messages", [])),
                    "first_message_content": request_body.get("messages", [{}])[0].get("content") if request_body.get("messages") else None
                }
            }
        )

    def _validate_request_and_model(self, requested_model: str, allowed_models: list, api_key: str, project_name: str, request_id: str, user_id: str) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        if not requested_model:
            error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
            logger.error("Model not specified in request", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail,
            )

        if allowed_models and requested_model not in allowed_models:
            error_detail = {"error": {"message": f"Model '{requested_model}' not allowed for this API key", "code": "model_not_allowed"}}
            logger.error(f"Model '{requested_model}' not allowed for API key", extra={"detail": error_detail, "api_key": api_key, "project_name": project_name, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_detail,
            )

        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        if not model_config:
            error_detail = {"error": {"message": f"Model '{requested_model}' not found in configuration", "code": "model_not_found"}}
            logger.error(f"Model '{requested_model}' not found in configuration", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail,
            )

        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        provider_config = current_config.get("providers", {}).get(provider_name)
        if not provider_config:
            error_detail = {"error": {"message": f"Provider '{provider_name}' for model '{requested_model}' not found in configuration", "code": "provider_not_found"}}
            logger.error(f"Provider '{provider_name}' for model '{requested_model}' not found", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
        return model_config, provider_name, provider_model_name, provider_config

    def _get_provider_instance(self, provider_config: Dict[str, Any], request_id: str, user_id: str):
        try:
            return get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            error_detail = {"error": {"message": f"Provider configuration error: {e}", "code": "provider_config_error"}}
            logger.error(f"Provider configuration error: {e}", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )

    async def _stream_response_handler(self, response_data: StreamingResponse, provider_type: str, requested_model: str, request_id: str, user_id: str):
        full_content = ""
        stream_completed_usage = None
        
        async for chunk in response_data.body_iterator:
            try:
                decoded_chunk = chunk.decode('utf-8')
                
                if decoded_chunk.startswith('data: '):
                    full_content, stream_completed_usage = self._process_openai_sse_chunk(decoded_chunk, full_content, stream_completed_usage)
                    yield chunk # Yield original chunk for OpenAI SSE
                elif provider_type == "ollama":
                    processed_chunk, new_full_content, new_stream_completed_usage = self._process_ollama_chunk(decoded_chunk, full_content, stream_completed_usage, requested_model, request_id)
                    full_content = new_full_content
                    stream_completed_usage = new_stream_completed_usage
                    if processed_chunk: # Only yield if there's a valid chunk to yield
                        yield processed_chunk
                else:
                    yield chunk
            except UnicodeDecodeError:
                pass # Handle cases where chunk is not valid UTF-8

        self._log_streaming_completion(request_id, user_id, requested_model, full_content, stream_completed_usage)
        yield b"data: [DONE]\n\n" # Ensure DONE message is sent at the very end

    def _process_openai_sse_chunk(self, decoded_chunk: str, full_content: str, stream_completed_usage: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        for line in decoded_chunk.split('\n'):
            if line.startswith('data: '):
                json_data = line[len('data: '):].strip()
                if json_data == '[DONE]':
                    continue
                try:
                    data = json.loads(json_data)
                    if 'choices' in data and len(data['choices']) > 0:
                        delta_content = data['choices'][0].get('delta', {}).get('content')
                        if delta_content:
                            full_content += delta_content
                    if 'usage' in data:
                        stream_completed_usage = data['usage']
                except json.JSONDecodeError:
                    pass
        return full_content, stream_completed_usage

    def _process_ollama_chunk(self, decoded_chunk: str, full_content: str, stream_completed_usage: Dict[str, Any], requested_model: str, request_id: str) -> Tuple[bytes, str, Dict[str, Any]]:
        processed_chunk = b""
        for line in decoded_chunk.split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get('done'):
                    if 'prompt_eval_count' in data:
                        stream_completed_usage = {
                            "prompt_tokens": data.get("prompt_eval_count", 0),
                            "completion_tokens": data.get("eval_count", 0)
                        }
                    elif 'usage' in data:
                        stream_completed_usage = data['usage']
                    # Do not return early, let the loop finish and _stream_response_handler handle [DONE]
                    continue
                
                delta_content = data.get('message', {}).get('content', '')
                if delta_content:
                    full_content += delta_content

                openai_chunk = {
                    "id": f"chatcmpl-{request_id}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": requested_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta_content},
                            "logprobs": None,
                            "finish_reason": None
                        }
                    ]
                }
                processed_chunk = f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
            except json.JSONDecodeError:
                pass
        return processed_chunk, full_content, stream_completed_usage

    def _log_streaming_completion(self, request_id: str, user_id: str, requested_model: str, full_content: str, stream_completed_usage: Dict[str, Any]):
        prompt_tokens = stream_completed_usage.get("prompt_tokens", 0) if stream_completed_usage else 0
        completion_tokens = stream_completed_usage.get("completion_tokens", 0) if stream_completed_usage else 0
        finish_reason = "stop"

        logger.info(
            "Chat Completion Response",
            extra={
                "log_type": "response",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "http_status_code": status.HTTP_200_OK,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_body_summary": {
                    "finish_reason": finish_reason,
                    "content_preview": full_content
                }
            }
        )

    def _log_non_streaming_response(self, request_id: str, user_id: str, requested_model: str, response_data: Dict[str, Any]):
        usage = response_data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        logger.info(
            "Chat Completion Response",
            extra={
                "log_type": "response",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "http_status_code": status.HTTP_200_OK,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_body_summary": {
                    "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                    "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                }
            }
        )

    def _log_http_exception(self, e: HTTPException, request_id: str, user_id: str, requested_model: str):
        logger.error(
            f"HTTPException from provider: {e.detail.get('error', {}).get('message', str(e))}",
            extra={
                "status_code": e.status_code,
                "detail": e.detail,
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "log_type": "error"
            }
        )

    def _log_unexpected_exception(self, e: Exception, request_id: str, user_id: str, requested_model: str):
        logger.error(
            f"An unexpected error occurred: {e}",
            extra={
                "detail": {"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}},
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "log_type": "error"
            },
            exc_info=True
        )
