"""Unit tests for src/core/usage_db.py — error logging and task tracking."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core import usage_db


@pytest.fixture(autouse=True)
def reset_tasks():
    usage_db._usage_tasks.clear()
    yield
    usage_db._usage_tasks.clear()


class TestRecordUsageErrorLogging:

    @pytest.mark.asyncio
    async def test_logs_error_on_db_failure(self):
        """A DB failure is logged (not silently swallowed)."""
        conn = MagicMock()
        conn.execute = AsyncMock(side_effect=RuntimeError("db down"))
        with patch("src.core.usage_db.get_connection", return_value=conn), \
             patch("src.core.usage_db.logger") as mock_logger:
            await usage_db.record_usage(
                project_name="p", model_id="m", endpoint="chat",
                prompt_tokens=1, completion_tokens=2,
                request_id="req-1",
            )
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_connection_is_silent(self):
        """No connection returns without logging an error."""
        with patch("src.core.usage_db.get_connection", return_value=None), \
             patch("src.core.usage_db.logger") as mock_logger:
            await usage_db.record_usage(
                project_name="p", model_id="m", endpoint="chat",
                prompt_tokens=1, completion_tokens=2,
            )
        mock_logger.error.assert_not_called()


class TestScheduleRecordUsage:

    @pytest.mark.asyncio
    async def test_task_is_tracked_and_discarded_on_success(self):
        """The created task is tracked, then removed on completion."""
        with patch("src.core.usage_db.record_usage", new=AsyncMock()):
            task = usage_db.schedule_record_usage(
                project_name="p", model_id="m", endpoint="chat",
                prompt_tokens=1, completion_tokens=2,
            )
            assert task is not None
            assert task in usage_db._usage_tasks
            await task
            assert task not in usage_db._usage_tasks

    @pytest.mark.asyncio
    async def test_failing_task_logs_warning(self):
        """A failing record task triggers a WARNING via the done callback."""
        with patch("src.core.usage_db.record_usage", new=AsyncMock(side_effect=RuntimeError("boom"))), \
             patch("src.core.usage_db.logger") as mock_logger:
            task = usage_db.schedule_record_usage(
                project_name="p", model_id="m", endpoint="chat",
                prompt_tokens=1, completion_tokens=2,
            )
            try:
                await task
            except RuntimeError:
                pass
            # Done callback is scheduled via call_soon; let it run.
            await asyncio.sleep(0)
        # Task must be discarded even on failure
        assert task not in usage_db._usage_tasks
        mock_logger.warning.assert_called_once()
