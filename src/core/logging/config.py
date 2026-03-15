"""
Simplified logging configuration and setup for the LLM Router.

This module provides centralized logging configuration with plain text formatting
instead of JSON, maintaining all functionality while reducing complexity.
"""

import logging
import os

from ...utils.unicode import decode_unicode_escapes


class UnicodeFormatter(logging.Formatter):
    """Custom formatter that decodes Unicode escape sequences in log messages."""

    def format(self, record):
        formatted = super().format(record)
        return decode_unicode_escapes(formatted)


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