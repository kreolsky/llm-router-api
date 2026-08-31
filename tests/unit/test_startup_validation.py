"""Unit tests for src/api/main.py — eager provider validation on startup."""

from unittest.mock import MagicMock, patch

import pytest

import src.providers as provider_registry
from src.api.main import _validate_providers


@pytest.fixture(autouse=True)
def reset_provider_cache():
    provider_registry._provider_cache.clear()
    yield
    provider_registry._provider_cache.clear()


def _cm_with_providers(providers):
    from src.core.config_manager import Settings
    cm = MagicMock()
    cm.get_config.return_value = {"providers": providers}
    # Real Settings so httpx client construction works
    cm.settings = Settings()
    return cm


class TestValidateProviders:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_valid_providers_pass(self):
        """All providers instantiate → no exception."""
        providers = {
            "ok": {"type": "openai", "base_url": "https://api.example.com", "api_key_env": "TEST_API_KEY"}
        }
        cm = _cm_with_providers(providers)
        # Should not raise
        await _validate_providers(cm)

    @pytest.mark.asyncio
    async def test_missing_env_key_collected_and_raises(self):
        """Missing env key for a provider → RuntimeError naming the provider."""
        providers = {
            "broken": {"type": "openai", "base_url": "https://api.example.com", "api_key_env": "DEFINITELY_MISSING_KEY"}
        }
        cm = _cm_with_providers(providers)
        with patch.dict("os.environ", {}, clear=True), pytest.raises(RuntimeError, match="broken"):
            await _validate_providers(cm)

    @pytest.mark.asyncio
    async def test_multiple_failures_all_reported(self):
        """Multiple bad providers are all listed in the error message."""
        providers = {
            "broken-a": {"type": "openai", "base_url": "https://a.example.com", "api_key_env": "MISSING_A"},
            "broken-b": {"type": "openai", "base_url": "https://b.example.com", "api_key_env": "MISSING_B"},
        }
        cm = _cm_with_providers(providers)
        with patch.dict("os.environ", {}, clear=True), pytest.raises(RuntimeError) as exc_info:
            await _validate_providers(cm)
        msg = str(exc_info.value)
        assert "broken-a" in msg
        assert "broken-b" in msg

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_valid_providers_cached_after_validation(self):
        """Successful validation populates the provider cache."""
        providers = {
            "ok": {"type": "openai", "base_url": "https://api.example.com", "api_key_env": "TEST_API_KEY"}
        }
        cm = _cm_with_providers(providers)
        await _validate_providers(cm)
        assert "ok" in provider_registry._provider_cache
