"""Authentication and authorization for the API gateway."""
import hmac
from fastapi import Security, HTTPException, status, Request
from fastapi.security import APIKeyHeader
from typing import Dict, Any, Tuple, List
from .error_handling import ErrorType, create_error
from .logging import logger

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def get_api_key(
    request: Request,
    api_key: str = Security(api_key_header)
) -> Tuple[str, str, List[str], List[str]]:
    """Authenticate request and return (project_name, api_key, allowed_models, allowed_endpoints).

    Strips "Bearer " prefix from Authorization header if present.
    Uses constant-time comparison to prevent timing attacks.
    Sets request.state.project_name as a side effect for downstream handlers.
    """
    config_manager = request.app.state.config_manager
    config = config_manager.get_config()

    logger.debug("Authentication attempt", extra={
        "auth": {
            "has_api_key": api_key is not None,
            "request_path": str(request.url.path)
        }
    })
    
    if not api_key:
        logger.warning("Authentication failed: missing API key", extra={
            "auth": {
                "error_type": "missing_api_key",
                "request_path": str(request.url.path)
            }
        })
        raise create_error(ErrorType.MISSING_API_KEY)
    
    # Remove "Bearer " prefix if present
    if api_key.startswith("Bearer "):
        api_key = api_key[len("Bearer "):]

    if config is None or "user_keys" not in config:
        logger.error("Server configuration error: user keys not loaded", extra={
            "auth": {
                "error_type": "config_error",
                "config_loaded": config is not None,
                "has_user_keys": config is not None and "user_keys" in config
            }
        })
        raise create_error(ErrorType.INTERNAL_SERVER_ERROR, error_details="Server configuration error: user keys not loaded")

    found_project = None
    for project_name, project_data in config["user_keys"].items():
        stored_key = project_data.get("api_key", "")
        # INVARIANT: constant-time comparison prevents timing attacks
        if stored_key and hmac.compare_digest(stored_key, api_key):
            found_project = project_name
            break

    if not found_project:
        logger.warning("Authentication failed: invalid API key", extra={
            "auth": {
                "error_type": "invalid_api_key",
                "request_path": str(request.url.path)
            }
        })
        raise create_error(ErrorType.INVALID_API_KEY)
    
    allowed_models = config["user_keys"][found_project].get("allowed_models") or []
    allowed_endpoints = config["user_keys"][found_project].get("allowed_endpoints") or []
    
    # SIDE EFFECT: sets project_name read by downstream handlers
    request.state.project_name = found_project

    logger.info("Authentication successful", extra={
        "auth": {
            "project_name": found_project,
            "allowed_models_count": len(allowed_models),
            "allowed_endpoints_count": len(allowed_endpoints),
            "request_path": str(request.url.path)
        }
    })
    
    return found_project, api_key, allowed_models, allowed_endpoints


def check_endpoint_access(endpoint_path: str):
    """Return a FastAPI dependency that checks if the user's key grants access to endpoint_path.

    Empty allowed_endpoints list means unrestricted access (default for admin keys).
    """
    from fastapi import Depends
    
    async def endpoint_checker(
        request: Request,
        auth_data: Tuple[str, str, List[str], List[str]] = Depends(get_api_key)
    ):
        user_id, _, _, allowed_endpoints = auth_data
        
        # WHY: empty allowed_endpoints means unrestricted access (default for admin keys)
        if not allowed_endpoints or endpoint_path in allowed_endpoints:
            return auth_data
            
        logger.warning("Endpoint access denied", extra={
            "auth": {
                "error_type": "endpoint_not_allowed",
                "user_id": user_id,
                "endpoint_path": endpoint_path,
                "allowed_endpoints": allowed_endpoints
            }
        })
        raise create_error(ErrorType.ENDPOINT_NOT_ALLOWED, endpoint_path=endpoint_path, user_id=user_id)
    
    return endpoint_checker
