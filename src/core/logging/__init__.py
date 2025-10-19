"""
Ultra-simple logging infrastructure for the LLM Router.

Provides a minimal Logger class focused on effective debugging and diagnostics.
"""

from .config import setup_logging
from .logger import Logger

# Создаем единый экземпляр логгера
_logger_instance = None

def get_logger():
    """Получить единый экземпляр логгера."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
    return _logger_instance

# Экспортируем единый логгер
logger = get_logger()

# Экспортируем только основные компоненты
__all__ = ['logger', 'Logger', 'setup_logging']