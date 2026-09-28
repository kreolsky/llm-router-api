"""Unit tests for src/core/logging — handler wiring and Logger exc_info forwarding."""

import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

import pytest

from src.core.logging.config import setup_logging
from src.core.logging.logger import Logger


def _file_handlers(logger):
    return [h for h in logger.handlers if isinstance(h, logging.FileHandler)]


class TestLogRotation:
    """File logs must rotate: debug.log carries full request/response bodies."""

    def test_file_handlers_rotate(self):
        """Every file handler is size-rotating, never an unbounded FileHandler."""
        with patch.dict("os.environ", {"LOG_LEVEL": "DEBUG"}, clear=False):
            logger = setup_logging()
        handlers = _file_handlers(logger)
        assert handlers, "expected at least one file handler"
        assert all(isinstance(h, RotatingFileHandler) for h in handlers)

    def test_rotation_limits_from_env(self):
        """LOG_MAX_BYTES / LOG_BACKUP_COUNT drive the rotation limits."""
        env = {"LOG_LEVEL": "DEBUG", "LOG_MAX_BYTES": "2048", "LOG_BACKUP_COUNT": "5"}
        with patch.dict("os.environ", env, clear=False):
            logger = setup_logging()
        for handler in _file_handlers(logger):
            assert handler.maxBytes == 2048
            assert handler.backupCount == 5

    def test_debug_handler_only_at_debug_level(self):
        """debug.log is added only when LOG_LEVEL=DEBUG."""
        with patch.dict("os.environ", {"LOG_LEVEL": "INFO"}, clear=False):
            logger = setup_logging()
        assert len(_file_handlers(logger)) == 1

    def test_defaults_are_bounded(self):
        """Without env overrides the limits are still finite."""
        env = {"LOG_LEVEL": "INFO"}
        with patch.dict("os.environ", env, clear=False):
            import os
            os.environ.pop("LOG_MAX_BYTES", None)
            os.environ.pop("LOG_BACKUP_COUNT", None)
            logger = setup_logging()
        for handler in _file_handlers(logger):
            assert handler.maxBytes > 0
            assert handler.backupCount > 0


class TestLoggerExcInfo:
    """exc_info=True must reach the log record at every level, not be dropped."""

    @pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
    def test_exc_info_forwarded(self, level, caplog):
        log = Logger()
        with caplog.at_level(logging.DEBUG, logger=log._logger.name):
            try:
                raise ValueError("boom")
            except ValueError:
                getattr(log, level)("x", exc_info=True, component="test")
        records = [r for r in caplog.records if r.getMessage() == "x"]
        assert records, f"no record emitted for {level}"
        assert records[-1].exc_info is not None
        assert records[-1].exc_info[0] is ValueError
