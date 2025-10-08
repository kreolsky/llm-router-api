import logging
import json
import os

logger = logging.getLogger("nnp-llm-router")

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        
        # Add custom attributes from the 'extra' dictionary if they exist
        # These are the fields we explicitly pass in our logger.info calls
        if hasattr(record, 'request_id'):
            log_record['request_id'] = record.request_id
        if hasattr(record, 'user_id'):
            log_record['user_id'] = record.user_id
        if hasattr(record, 'model_id'):
            log_record['model_id'] = record.model_id
        if hasattr(record, 'log_type'):
            log_record['log_type'] = record.log_type
        if hasattr(record, 'method'):
            log_record['method'] = record.method
        if hasattr(record, 'url'):
            log_record['url'] = record.url
        if hasattr(record, 'request_body_summary'):
            log_record['request_body_summary'] = record.request_body_summary
        if hasattr(record, 'http_status_code'):
            log_record['http_status_code'] = record.http_status_code
        if hasattr(record, 'process_time_ms'):
            log_record['process_time_ms'] = record.process_time_ms
        if hasattr(record, 'prompt_tokens'):
            log_record['prompt_tokens'] = record.prompt_tokens
        if hasattr(record, 'completion_tokens'):
            log_record['completion_tokens'] = record.completion_tokens
        if hasattr(record, 'total_tokens'):
            log_record['total_tokens'] = record.total_tokens
        if hasattr(record, 'prompt_cost'):
            log_record['prompt_cost'] = record.prompt_cost
        if hasattr(record, 'completion_cost'):
            log_record['completion_cost'] = record.completion_cost
        if hasattr(record, 'total_cost'):
            log_record['total_cost'] = record.total_cost
        if hasattr(record, 'response_body_summary'):
            log_record['response_body_summary'] = record.response_body_summary
        if hasattr(record, 'error_message'):
            log_record['error_message'] = record.error_message
        if hasattr(record, 'error_code'):
            log_record['error_code'] = record.error_code
        if hasattr(record, 'http_status_code'):
            log_record['http_status_code'] = record.http_status_code
        if hasattr(record, 'detail'): # For HTTPException details
            log_record['detail'] = record.detail
        if hasattr(record, 'api_key'): # For logging sensitive info in errors, if needed
            log_record['api_key'] = record.api_key
        if hasattr(record, 'project_name'): # For logging sensitive info in errors, if needed
            log_record['project_name'] = record.project_name
        
        # DEBUG logging fields for full JSON data logging
        if hasattr(record, 'debug_json_data'):
            log_record['debug_json_data'] = record.debug_json_data
        if hasattr(record, 'debug_data_flow'):
            log_record['debug_data_flow'] = record.debug_data_flow  # 'incoming', 'outgoing', 'to_provider', 'from_provider'
        if hasattr(record, 'debug_component'):
            log_record['debug_component'] = record.debug_component  # 'middleware', 'chat_service', 'provider', etc.
        
        # Handle exception information
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)
        
        return json.dumps(log_record, ensure_ascii=False)

def setup_logging():
    # Get log level from environment variable
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    
    logger = logging.getLogger("nnp-llm-router")
    logger.setLevel(getattr(logging, log_level))

    # Ensure logs directory exists
    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_FILE = os.path.join(LOG_DIR, "app.log")

    # File handler for general logs
    file_handler = logging.FileHandler(LOG_FILE)
    file_formatter = JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)  # Always at least INFO level for main log
    logger.addHandler(file_handler)

    # DEBUG log handler - separate file for debug logs
    if log_level == "DEBUG":
        DEBUG_LOG_FILE = os.path.join(LOG_DIR, "debug.log")
        debug_handler = logging.FileHandler(DEBUG_LOG_FILE)
        debug_handler.setFormatter(JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
        debug_handler.setLevel(logging.DEBUG)
        logger.addHandler(debug_handler)
        
        # Also add DEBUG to console if in debug mode
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)
    else:
        # Console handler for non-debug mode
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

    # Ensure logger propagates to handlers
    logger.propagate = True
