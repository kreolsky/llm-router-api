class ProviderStreamError(Exception):
    """Custom exception for errors occurring during provider streaming."""
    def __init__(self, message: str, status_code: int = 500, error_code: str = "provider_stream_error", original_exception: Exception = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.original_exception = original_exception

class ProviderAPIError(Exception):
    """Custom exception for errors from provider API responses (e.g., 4xx/5xx)."""
    def __init__(self, message: str, status_code: int, error_code: str = "provider_api_error", original_response_text: str = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.original_response_text = original_response_text

class ProviderNetworkError(Exception):
    """Custom exception for network or connection errors to providers."""
    def __init__(self, message: str, original_exception: Exception = None):
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception