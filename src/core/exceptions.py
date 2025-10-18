from .logging import logger

class ProviderStreamError(Exception):
    """Custom exception for errors occurring during provider streaming."""
    def __init__(self, message: str, status_code: int = 500, error_code: str = "provider_stream_error", original_exception: Exception = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.original_exception = original_exception
        
        # Log the exception when it's created
        logger.error(f"Provider stream error: {message}", extra={
            "exception": {
                "type": "ProviderStreamError",
                "error_code": error_code,
                "status_code": status_code,
                "has_original_exception": original_exception is not None,
                "original_exception_type": type(original_exception).__name__ if original_exception else None
            }
        }, exc_info=original_exception is not None)

class ProviderAPIError(Exception):
    """Custom exception for errors from provider API responses (e.g., 4xx/5xx)."""
    def __init__(self, message: str, status_code: int, error_code: str = "provider_api_error", original_response_text: str = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.original_response_text = original_response_text
        
        # Log the exception when it's created
        logger.error(f"Provider API error: {message}", extra={
            "exception": {
                "type": "ProviderAPIError",
                "error_code": error_code,
                "status_code": status_code,
                "has_original_response": original_response_text is not None,
                "response_preview": original_response_text[:200] + "..." if original_response_text and len(original_response_text) > 200 else original_response_text
            }
        })

class ProviderNetworkError(Exception):
    """Custom exception for network or connection errors to providers."""
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception
        
        # Log the exception when it's created
        logger.error(f"Provider network error: {message}", extra={
            "exception": {
                "type": "ProviderNetworkError",
                "has_original_exception": original_exception is not None,
                "original_exception_type": type(original_exception).__name__ if original_exception else None
            }
        }, exc_info=original_exception is not None)