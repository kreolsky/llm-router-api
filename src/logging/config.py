import logging
import json
import os
from logging.handlers import RotatingFileHandler

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
        
        # Handle exception information
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)
        
        return json.dumps(log_record, ensure_ascii=False)

def setup_logging():
    logger = logging.getLogger("nnp-llm-router")
    logger.setLevel(logging.INFO)

    # Ensure logs directory exists
    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_FILE = os.path.join(LOG_DIR, "app.log")

    # File handler
    file_handler = logging.FileHandler(LOG_FILE)
    file_formatter = JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Ensure logger propagates to handlers
    logger.propagate = True
