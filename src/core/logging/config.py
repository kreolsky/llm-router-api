"""
Simplified logging configuration and setup for the LLM Router.

This module provides centralized logging configuration with plain text formatting
instead of JSON, maintaining all functionality while reducing complexity.
"""

import logging
import os


def setup_logging():
    """
    Setup logging configuration with handlers and formatters.
    
    Returns:
        logging.Logger: Configured logger instance
    """
    # Get log level from environment variable
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    
    logger = logging.getLogger("nnp-llm-router")
    logger.setLevel(getattr(logging, log_level))

    # Ensure logs directory exists
    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_FILE = os.path.join(LOG_DIR, "app.log")

    # Create a simple formatter for plain text logging
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    )

    # File handler for general logs
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)  # Always at least INFO level for main log
    logger.addHandler(file_handler)

    # DEBUG log handler - separate file for debug logs
    if log_level == "DEBUG":
        DEBUG_LOG_FILE = os.path.join(LOG_DIR, "debug.log")
        debug_handler = logging.FileHandler(DEBUG_LOG_FILE)
        debug_handler.setFormatter(formatter)
        debug_handler.setLevel(logging.DEBUG)
        logger.addHandler(debug_handler)
        
        # Also add DEBUG to console if in debug mode
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)
    else:
        # Console handler for non-debug mode
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

    # Ensure logger propagates to handlers
    logger.propagate = True
    
    return logger