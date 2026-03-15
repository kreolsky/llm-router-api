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
        """Decode \\uXXXX escape sequences in log messages.

        Sibling of ErrorLogger._decode_unicode_escapes with the same purpose.
        Duplicated here because the formatter runs inside the logging pipeline
        and importing from error_logger would create a circular dependency.
        """
        if not text:
            return text

        try:
            # WHY: JSON error objects with \u escapes decode cleanly via json roundtrip
            if '"error":' in text and '\\u' in text:
                decoded = json.loads(text)
                if isinstance(decoded, dict):
                    return json.dumps(decoded, ensure_ascii=False)
        except (json.JSONDecodeError, ValueError):
            pass

        # WHY: fallback regex for non-JSON texts with \u escapes
        def replace_unicode(match):
            hex_code = match.group(1)
            try:
                return chr(int(hex_code, 16))
            except ValueError:
                return match.group(0)
        
        return self.unicode_pattern.sub(replace_unicode, text)
    
    def format(self, record):
        formatted = super().format(record)
        formatted = self._decode_unicode_escapes(formatted)
        return formatted


def setup_logging():
    """Configure and return the project-wide logger.

    Creates log directory as a side effect. Adds a debug file handler
    when LOG_LEVEL=DEBUG.
    """
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    logger = logging.getLogger("nnp-llm-router")
    logger.setLevel(getattr(logging, log_level))

    # INVARIANT: handlers cleared on every call to prevent duplicate log entries
    logger.handlers.clear()

    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = UnicodeFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    )

    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "app.log"))
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    if log_level == "DEBUG":
        debug_handler = logging.FileHandler(os.path.join(LOG_DIR, "debug.log"))
        debug_handler.setFormatter(formatter)
        debug_handler.setLevel(logging.DEBUG)
        logger.addHandler(debug_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if log_level == "DEBUG" else logging.INFO)
    logger.addHandler(console_handler)

    return logger