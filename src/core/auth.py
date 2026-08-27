"""Authentication and authorization for the API gateway."""
# SYSTEM: auth — bearer authentication (constant-time key comparison) and per-key model access control
import hashlib
import hmac

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .context import RequestContext
from .error_handling import ErrorType, create_error
from .logging import logger
from .usage_db import request_stats

bearer_scheme = HTTPBearer(auto_error=False)

async def get_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
) -> tuple[str, str, list[str], list[str]]:
    """Authenticate request and return (project_name, api_key, allowed_models, allowed_endpoints).

    Uses HTTPBearer scheme to extract token from Authorization header.
    Uses constant-time comparison to prevent timing attacks.
    Rebuilds the typed RequestContext on request.state.request_context with
    project_name attached (via ctx.with_project_name(...)) for downstream handlers.
    """
    config_manager = request.app.state.config_manager
    config = config_manager.get_config()

    api_key = credentials.credentials if credentials else None

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
        # Enrich the stats holder before raising: the row will carry a
        # truncated SHA-256 hash of the presented (invalid) key.
        request_stats(request).api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8]
        logger.warning("Authentication failed: invalid API key", extra={
            "auth": {
                "error_type": "invalid_api_key",
                "request_path": str(request.url.path)
            }
        })
        raise create_error(ErrorType.INVALID_API_KEY)
    
    allowed_models = config["user_keys"][found_project].get("allowed_models") or []
    allowed_endpoints = config["user_keys"][found_project].get("allowed_endpoints") or []
    
    # SIDE EFFECT: attach project_name to the typed RequestContext read by downstream handlers
    ctx: RequestContext = getattr(request.state, "request_context", None)
    if ctx is not None:
        request.state.request_context = ctx.with_project_name(found_project)
    else:
        request.state.request_context = RequestContext(
            request_id="unknown", project_name=found_project
        )

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
    async def endpoint_checker(
        request: Request,
        auth_data: tuple[str, str, list[str], list[str]] = Depends(get_api_key)
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
