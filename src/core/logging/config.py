"""
Simplified logging configuration and setup for the LLM Router.

This module provides centralized logging configuration with plain text formatting
instead of JSON, maintaining all functionality while reducing complexity.
"""

import logging
import os
import json
import re


class UnicodeFormatter(logging.Formatter):
    """
    Custom formatter that decodes Unicode escape sequences in log messages.
    """
    
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        # Pattern to match Unicode escape sequences
        self.unicode_pattern = re.compile(r'\\u([0-9a-fA-F]{4})')
    
    def _decode_unicode_escapes(self, text):
        """
        Decode Unicode escape sequences in the given text.
        
        Args:
            text (str): Text that may contain Unicode escape sequences
            
        Returns:
            str: Text with Unicode escape sequences decoded to actual characters
        """
        if not text:
            return text
            
        # First try to decode if it's a JSON string
        try:
            # Check if the text looks like it contains JSON with Unicode escapes
            if '"error":' in text and '\\u' in text:
                # Try to parse and re-encode to decode Unicode
                decoded = json.loads(text)
                if isinstance(decoded, dict):
                    return json.dumps(decoded, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Fallback: manually decode Unicode escape sequences
        def replace_unicode(match):
            hex_code = match.group(1)
            try:
                return chr(int(hex_code, 16))
            except ValueError:
                return match.group(0)
        
        return self.unicode_pattern.sub(replace_unicode, text)
    
    def format(self, record):
        """
        Format the log record, decoding Unicode escape sequences in the message.
        """
        # Format the record using the parent formatter
        formatted = super().format(record)
        
        # Decode Unicode escape sequences in the formatted message
        formatted = self._decode_unicode_escapes(formatted)
        
        return formatted


def setup_logging():
    """
    Единая настройка логирования для всего проекта.
    
    Returns:
        logging.Logger: Configured logger instance
    """
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    
    # Создаем основной логгер
    logger = logging.getLogger("nnp-llm-router")
    logger.setLevel(getattr(logging, log_level))
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    # Создаем директорию для логов
    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # Единый форматтер для всех обработчиков с поддержкой Unicode
    formatter = UnicodeFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    )
    
    # Файловый обработчик (всегда)
    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "app.log"))
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    
    # Обработчик для DEBUG (если включен)
    if log_level == "DEBUG":
        debug_handler = logging.FileHandler(os.path.join(LOG_DIR, "debug.log"))
        debug_handler.setFormatter(formatter)
        debug_handler.setLevel(logging.DEBUG)
        logger.addHandler(debug_handler)
    
    # Консольный обработчик (уровень зависит от LOG_LEVEL)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if log_level == "DEBUG" else logging.INFO)
    logger.addHandler(console_handler)
    
    return logger