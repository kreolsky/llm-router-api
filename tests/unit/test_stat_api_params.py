"""Unit tests for the /stat/api `days` query parameter contract.

The dashboard's "All" button sends `days=` (empty) — that must stay "no day
filter" (200 unfiltered). Non-numeric input must answer 422 in the
OpenRouter envelope instead of ValueError → 500. Endpoints are called
directly (they are plain functions); the DB layer is patched out.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.api import main as api_main


def _assert_422_envelope(exc_info, raw_value: str):
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["error"]["code"] == 422
    assert "days" in detail["error"]["message"]
    assert raw_value in detail["error"]["message"]


class TestStatUsageDays:

    @pytest.mark.asyncio
    async def test_non_numeric_days_raises_422_envelope_not_500(self):
        with pytest.raises(HTTPException) as exc_info:
            await api_main.stat_usage(users="", models="", days="abc", _=None)
        _assert_422_envelope(exc_info, "abc")

    @pytest.mark.asyncio
    async def test_empty_days_means_unfiltered(self):
        with patch.object(api_main, "get_usage_data", new_callable=AsyncMock) as get_usage:
            await api_main.stat_usage(users="", models="", days="", _=None)
            get_usage.assert_awaited_once_with([], [], None)

    @pytest.mark.asyncio
    async def test_numeric_days_is_parsed(self):
        with patch.object(api_main, "get_usage_data", new_callable=AsyncMock) as get_usage:
            await api_main.stat_usage(users="", models="", days="7", _=None)
            get_usage.assert_awaited_once_with([], [], 7)


class TestStatSummaryDays:

    @pytest.mark.asyncio
    async def test_non_numeric_days_raises_422_envelope_not_500(self):
        with pytest.raises(HTTPException) as exc_info:
            await api_main.stat_summary(users="", models="", days="1x", _=None)
        _assert_422_envelope(exc_info, "1x")

    @pytest.mark.asyncio
    async def test_empty_days_means_unfiltered(self):
        with patch.object(api_main, "get_summary", new_callable=AsyncMock) as get_summary:
            await api_main.stat_summary(users="", models="", days="", _=None)
            get_summary.assert_awaited_once_with([], [], None)


class TestStatRequestsDays:

    @pytest.mark.asyncio
    async def test_non_numeric_days_raises_422_envelope_not_500(self):
        with pytest.raises(HTTPException) as exc_info:
            await api_main.stat_requests(
                users="", models="", providers="", status="all", error_code="",
                request_id="", days="около-7", limit=50, offset=0, _=None,
            )
        _assert_422_envelope(exc_info, "около-7")

    @pytest.mark.asyncio
    async def test_empty_days_means_unfiltered(self):
        with patch.object(api_main, "get_requests", new_callable=AsyncMock) as get_requests:
            await api_main.stat_requests(
                users="", models="", providers="", status="all", error_code="",
                request_id="", days="", limit=50, offset=0, _=None,
            )
            get_requests.assert_awaited_once_with([], [], [], "all", "", "", None, limit=50, offset=0)
