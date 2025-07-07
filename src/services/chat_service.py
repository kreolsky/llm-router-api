import httpx
import json
import time # Added import for time
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
        self.model_service = model_service # Store ModelService instance

    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list]) -> Any:
        project_name, api_key, allowed_models = auth_data
        request_id = request.state.request_id
        user_id = project_name # Using project_name as user_id

        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})

        request_body = await request.json()
        requested_model = request_body.get("model")

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

        if not requested_model:
            error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
            logger.error("Model not specified in request", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail,
            )

        if allowed_models and len(allowed_models) > 0:
            if requested_model not in allowed_models:
                error_detail = {"error": {"message": f"Model '{requested_model}' not allowed for this API key", "code": "model_not_allowed"}}
                logger.error(f"Model '{requested_model}' not allowed for API key", extra={"detail": error_detail, "api_key": api_key, "project_name": project_name, "request_id": request_id, "user_id": user_id, "log_type": "error"})
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=error_detail,
                )

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

        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            error_detail = {"error": {"message": f"Provider configuration error: {e}", "code": "provider_config_error"}}
            logger.error(f"Provider configuration error: {e}", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
        
        try:
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            # If the provider returns a StreamingResponse, handle it as a stream
            if isinstance(response_data, StreamingResponse):
                # For streaming responses, we need to iterate through the stream
                # to get the full content and calculate tokens/cost from provider
                provider_type = provider_config.get("type")
                async def generate_and_log(provider_type: str):
                    full_content = ""
                    stream_completed_usage = None
                    
                    async for chunk in response_data.body_iterator:
                        try:
                            decoded_chunk = chunk.decode('utf-8')
                            
                            # Handle OpenAI-style SSE (data: {json})
                            if decoded_chunk.startswith('data: '):
                                for line in decoded_chunk.split('\n'):
                                    if line.startswith('data: '):
                                        json_data = line[len('data: '):].strip()
                                        if json_data == '[DONE]':
                                            yield b"data: [DONE]\n\n"
                                            continue
                                        try:
                                            data = json.loads(json_data)
                                            # Accumulate content from delta
                                            if 'choices' in data and len(data['choices']) > 0:
                                                delta_content = data['choices'][0].get('delta', {}).get('content')
                                                if delta_content:
                                                    full_content += delta_content
                                            # Check for usage object (typically in the last chunk)
                                            if 'usage' in data:
                                                stream_completed_usage = data['usage']
                                            yield f"data: {json.dumps(data)}\n\n".encode('utf-8')
                                        except json.JSONDecodeError:
                                            pass # Malformed JSON, ignore or log
                            
                            # Handle Ollama-style raw JSON (no "data: " prefix)
                            elif provider_type == "ollama":
                                for line in decoded_chunk.split('\n'):
                                    line = line.strip()
                                    if not line:
                                        continue

                                    try:
                                        data = json.loads(line)
                                        
                                        # Check for 'done' field to identify the last chunk and usage
                                        if data.get('done'):
                                            if 'prompt_eval_count' in data: # Ollama specific usage
                                                stream_completed_usage = {
                                                    "prompt_tokens": data.get("prompt_eval_count", 0),
                                                    "completion_tokens": data.get("eval_count", 0)
                                                }
                                            elif 'usage' in data: # OpenAI-like usage
                                                stream_completed_usage = data['usage']
                                            
                                            # Send [DONE] message
                                            yield b"data: [DONE]\n\n"
                                            continue # Stop processing after DONE

                                        # Extract content from Ollama's message structure
                                        delta_content = data.get('message', {}).get('content', '')
                                        if delta_content:
                                            full_content += delta_content

                                        # Construct OpenAI-compatible streaming chunk
                                        openai_chunk = {
                                            "id": f"chatcmpl-{request_id}", # Re-use request_id for consistency
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()), # Use current timestamp
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
                                        yield f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')

                                    except json.JSONDecodeError:
                                        pass # Malformed JSON, ignore or log
                            else:
                                # Fallback for unknown streaming formats, yield as is
                                yield chunk
                        except UnicodeDecodeError:
                            pass # Handle cases where chunk is not valid UTF-8

                    # After the stream is complete, log the full information
                    prompt_tokens = 0
                    completion_tokens = 0
                    finish_reason = "stop" # Default finish reason

                    if stream_completed_usage:
                        prompt_tokens = stream_completed_usage.get("prompt_tokens", 0)
                        completion_tokens = stream_completed_usage.get("completion_tokens", 0)

                    logger.info(
                        "Chat Completion Response", # Log as a full response after stream
                        extra={
                            "log_type": "response",
                            "request_id": request_id,
                            "user_id": user_id,
                            "model_id": requested_model,
                            "http_status_code": status.HTTP_200_OK, # Assuming 200 for successful stream
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "response_body_summary": {
                                "finish_reason": finish_reason,
                                "content_preview": full_content
                            }
                        }
                    )
                return StreamingResponse(generate_and_log(provider_type), media_type=response_data.media_type)
            
            else:
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
                        "http_status_code": status.HTTP_200_OK, # Assuming 200 for successful non-streaming
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "response_body_summary": {
                            "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                            "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        }
                    }
                )
                return JSONResponse(content=response_data)
            
        except HTTPException as e:
            logger.error(f"HTTPException from provider: {e.detail.get('error', {}).get('message', str(e))}", extra={"status_code": e.status_code, "detail": e.detail, "request_id": request_id, "user_id": user_id, "model_id": requested_model, "log_type": "error"})
            raise e
        except Exception as e:
            error_detail = {"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}}
            logger.error(f"An unexpected error occurred: {e}", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "model_id": requested_model, "log_type": "error"}, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
