from fastapi import Security, HTTPException, status, Request
from fastapi.security import APIKeyHeader
from typing import Dict, Any

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def get_api_key(
    request: Request,
    api_key: str = Security(api_key_header)
) -> str:
    config_manager = request.app.state.config_manager
    config = config_manager.get_config()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "API key missing", "code": "missing_api_key"}},
        )
    
    # Remove "Bearer " prefix if present
    if api_key.startswith("Bearer "):
        api_key = api_key[len("Bearer "):]

    if config is None or "user_keys" not in config:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"message": "Server configuration error: user keys not loaded", "code": "server_config_error"}},
        )

    found_project = None
    for project_name, project_data in config["user_keys"].items():
        if project_data.get("api_key") == api_key:
            found_project = project_name
            break

    if not found_project:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"message": "Invalid API key", "code": "invalid_api_key"}},
        )
    
    allowed_models = config["user_keys"][found_project].get("allowed_models", [])
    request.state.project_name = found_project # Store project_name in request.state
    return found_project, api_key, allowed_models
