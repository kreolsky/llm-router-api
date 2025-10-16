from fastapi import Security, HTTPException, status, Request
from fastapi.security import APIKeyHeader
from typing import Dict, Any, Tuple, List
from .error_handling import ErrorHandler, ErrorContext

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def get_api_key(
    request: Request,
    api_key: str = Security(api_key_header)
) -> Tuple[str, str, List[str], List[str]]:
    config_manager = request.app.state.config_manager
    config = config_manager.get_config()
    if not api_key:
        context = ErrorContext()
        raise ErrorHandler.handle_auth_errors("missing_api_key", context)
    
    # Remove "Bearer " prefix if present
    if api_key.startswith("Bearer "):
        api_key = api_key[len("Bearer "):]

    if config is None or "user_keys" not in config:
        context = ErrorContext()
        raise ErrorHandler.handle_internal_server_error(
            "Server configuration error: user keys not loaded",
            context
        )

    found_project = None
    for project_name, project_data in config["user_keys"].items():
        if project_data.get("api_key") == api_key:
            found_project = project_name
            break

    if not found_project:
        context = ErrorContext()
        raise ErrorHandler.handle_auth_errors("invalid_api_key", context)
    
    allowed_models = config["user_keys"][found_project].get("allowed_models", [])
    allowed_endpoints = config["user_keys"][found_project].get("allowed_endpoints", [])
    
    request.state.project_name = found_project # Store project_name in request.state
    return found_project, api_key, allowed_models, allowed_endpoints


def check_endpoint_access(endpoint_path: str):
    """
    Декоратор для проверки доступа пользователя к конкретному endpoint.
    
    Args:
        endpoint_path: Путь к endpoint для проверки
        
    Returns:
        Функцию-зависимость для FastAPI
    """
    from fastapi import Depends
    
    async def endpoint_checker(
        request: Request,
        auth_data: Tuple[str, str, List[str], List[str]] = Depends(get_api_key)
    ):
        user_id, _, _, allowed_endpoints = auth_data
        
        # Если список разрешенных endpoints пуст, доступ разрешен ко всем endpoints
        if not allowed_endpoints or endpoint_path in allowed_endpoints:
            return auth_data
            
        context = ErrorContext(endpoint_path=endpoint_path, user_id=user_id)
        raise ErrorHandler.handle_endpoint_not_allowed(endpoint_path, context)
    
    return endpoint_checker
