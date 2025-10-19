# Corrected Ultra Minimal Transcription Service Refactoring

## Requirements

1. If model is passed → use that model
2. If no model is passed and user has endpoint access → use DEFAULT_STT_MODEL from .env
3. Log when using default model (request without model)
4. Single code path for request with model
5. Use correct access check (empty list = access to all models)

## Implementation

### Simplified Main Method

```python
async def create_transcription(
    self,
    audio_file: UploadFile,
    model_id: Optional[str] = None,
    auth_data: Tuple[str, str, Any, Any] = None,
    response_format: str = "json",
    temperature: float = 0.0,
    language: str = None,
    return_timestamps: bool = False
) -> Any:
    import os
    audio_data = await audio_file.read()
    user_id, api_key, allowed_models, allowed_endpoints = auth_data
    
    # Determine which model to use
    if model_id:
        # Model specified by user
        # Check model access using the same logic as model_service.py
        if allowed_models and model_id not in allowed_models:
            logger.warning(f"User {user_id} denied access to model {model_id}", extra={
                "user_id": user_id,
                "model_id": model_id,
                "operation": "access_denied"
            })
            context = ErrorContext(user_id=user_id, model_id=model_id)
            raise ErrorHandler.handle_model_not_allowed(model_id, context)
    else:
        # No model specified, use default from .env
        model_id = os.getenv("DEFAULT_STT_MODEL")
        if not model_id:
            context = ErrorContext(user_id=user_id)
            raise ErrorHandler.handle_internal_server_error(
                "DEFAULT_STT_MODEL not configured", context
            )
        
        # Log that we're using default model
        logger.info(f"User {user_id} requesting transcription without model, using default", extra={
            "user_id": user_id,
            "default_model": model_id,
            "operation": "transcription_without_model"
        })
    
    # Create error context
    context = ErrorContext(user_id=user_id, model_id=model_id)
    
    try:
        # Get model configuration
        model_config = await self.model_service.retrieve_model(model_id, auth_data)
        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name")
        
        if not provider_name or not provider_model_name:
            raise ErrorHandler.handle_provider_config_error(
                f"Model '{model_id}' is not correctly configured",
                context
            )
        
        # Get provider configuration
        provider_config = self.config_manager.get_config().get("providers", {}).get(provider_name)
        if not provider_config:
            context.provider_name = provider_name
            raise ErrorHandler.handle_provider_not_found(provider_name, model_id, context)
        
        # Create provider instance
        provider_instance = await self._get_provider_instance(provider_config)
        
        # Send request to provider
        response = await provider_instance.transcriptions(
            audio_data=audio_data,
            filename=audio_file.filename,
            content_type=audio_file.content_type,
            model_id=provider_model_name,
            api_key=api_key,
            base_url=provider_config.get("base_url"),
            response_format=response_format,
            temperature=temperature,
            return_timestamps=return_timestamps,
            language=language
        )
        
        return response
        
    except HTTPException as e:
        # Re-raise HTTPExceptions from our error handler (already logged)
        raise e
    except Exception as e:
        raise ErrorHandler.handle_internal_server_error(str(e), context, e)
```

## Summary of Changes

1. **Remove methods**: Delete `_process_transcription_request` and `_proxy_transcription_request`
2. **Move all logic to main method**: `create_transcription` handles everything
3. **Remove final_model_id variable**: Use model_id directly
4. **Keep existing access check**: `if allowed_models and model_id not in allowed_models:`
5. **Add environment variable**: `DEFAULT_STT_MODEL` in `.env`

## Environment Variable

Add to `.env` file:
```
DEFAULT_STT_MODEL=stt/dummy
```

## Benefits

1. **Simplest possible**: All logic in one method
2. **Correct access check**: Uses the same pattern as other services
3. **No extra variables**: Uses model_id directly
4. **Proper logging**: Logs when using default model

This is the corrected ultra-minimal implementation that follows the project's access control pattern.