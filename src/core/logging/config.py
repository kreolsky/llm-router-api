"""
Simplified logging configuration and setup for the LLM Router.

This module provides centralized logging configuration with plain text formatting
instead of JSON, maintaining all functionality while reducing complexity.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from ...utils.unicode import decode_unicode_escapes

# WHY: plain FileHandler grows without bound. debug.log carries full request and
# response bodies, so on a busy router it fills the disk — and the disk it fills
# is the one holding data/usage.db. Sizes are env-tunable per deployment.
_DEFAULT_MAX_BYTES = 50 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 3


def _rotating_handler(path: str, level: int, formatter: logging.Formatter) -> RotatingFileHandler:
    """Build a size-rotating file handler (LOG_MAX_BYTES / LOG_BACKUP_COUNT)."""
    handler = RotatingFileHandler(
        path,
        maxBytes=int(os.environ.get("LOG_MAX_BYTES", _DEFAULT_MAX_BYTES)),
        backupCount=int(os.environ.get("LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT)),
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    handler.setLevel(level)
    return handler


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

    logger.addHandler(
        _rotating_handler(os.path.join(LOG_DIR, "app.log"), logging.INFO, formatter)
    )

    if log_level == "DEBUG":
        logger.addHandler(
            _rotating_handler(os.path.join(LOG_DIR, "debug.log"), logging.DEBUG, formatter)
        )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if log_level == "DEBUG" else logging.INFO)
    logger.addHandler(console_handler)

    return logger