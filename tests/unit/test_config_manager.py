"""Unit tests for src/core/config_manager.py — ConfigManager class."""

from unittest.mock import patch, mock_open, MagicMock, call
import yaml

import pytest

from src.core.config_manager import ConfigManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROVIDERS_YAML = "providers:\n  openai:\n    type: openai\n    base_url: https://api.openai.com\n"
MODELS_YAML = "models:\n  gpt-4:\n    provider: openai\n"
USER_KEYS_YAML = "user_keys:\n  test-key:\n    project_name: test\n"

ALL_YAMLS = {
    "providers.yaml": PROVIDERS_YAML,
    "models.yaml": MODELS_YAML,
    "user_keys.yaml": USER_KEYS_YAML,
}


def _multi_open(file_map):
    """Return a side_effect for builtins.open that dispatches by file path suffix."""
    from io import StringIO
    from unittest.mock import MagicMock
    import contextlib

    def _side_effect(path, *args, **kwargs):
        for key, content in file_map.items():
            if path.endswith(key):
                sio = StringIO(content)
                # Make it usable as context manager
                sio.__enter__ = lambda s: s
                sio.__exit__ = lambda s, *a: None
                return sio
        raise FileNotFoundError(f"No such file: {path}")

    return _side_effect


def _build_config_manager(file_map=None, env=None):
    """Build ConfigManager with mocked file I/O and env."""
    if file_map is None:
        file_map = ALL_YAMLS
    env_vars = env or {}

    with patch("builtins.open", side_effect=_multi_open(file_map)), \
         patch("os.path.exists", return_value=True), \
         patch("os.path.getmtime", return_value=1000.0), \
         patch.dict("os.environ", env_vars, clear=False), \
         patch("src.core.config_manager.logger"):
        cm = ConfigManager(config_dir="/fake/config")
    return cm


# ===================================================================
# _load_config
# ===================================================================

class TestLoadConfig:

    def test_loads_all_three_yaml_files(self):
        """Loads providers, models, and user_keys from YAML files correctly."""
        cm = _build_config_manager()
        config = cm.get_config()
        assert "providers" in config
        assert "models" in config
        assert "user_keys" in config
        assert config["providers"]["openai"]["type"] == "openai"
        assert config["models"]["gpt-4"]["provider"] == "openai"

    def test_missing_file_fail_on_error_true_raises(self):
        """Missing file with fail_on_error=True raises RuntimeError."""
        file_map = {
            "providers.yaml": PROVIDERS_YAML,
            # models.yaml missing
            "user_keys.yaml": USER_KEYS_YAML,
        }
        with pytest.raises(RuntimeError, match="Critical config file missing"):
            with patch("builtins.open", side_effect=_multi_open(file_map)), \
                 patch("os.path.exists", return_value=True), \
                 patch("os.path.getmtime", return_value=1000.0), \
                 patch("src.core.config_manager.logger"):
                ConfigManager(config_dir="/fake/config")

    def test_missing_file_fail_on_error_false_partial(self):
        """Missing file with fail_on_error=False returns partial config."""
        cm = _build_config_manager()
        # Call _load_config with fail_on_error=False, simulating a missing file
        file_map_missing = {
            "providers.yaml": PROVIDERS_YAML,
            "user_keys.yaml": USER_KEYS_YAML,
        }
        with patch("builtins.open", side_effect=_multi_open(file_map_missing)), \
             patch("src.core.config_manager.logger"):
            partial_config = cm._load_config(fail_on_error=False)
        assert "providers" in partial_config
        assert "user_keys" in partial_config
        assert "models" not in partial_config

    def test_invalid_yaml_fail_on_error_true_raises(self):
        """Invalid YAML with fail_on_error=True raises RuntimeError."""
        file_map = {
            "providers.yaml": PROVIDERS_YAML,
            "models.yaml": ": invalid: yaml: [[[",
            "user_keys.yaml": USER_KEYS_YAML,
        }
        # The ": invalid: yaml: [[[" is actually parseable by some YAML parsers
        # so let's force a YAML error via mock
        cm = _build_config_manager()

        def _open_with_bad_yaml(path, *args, **kwargs):
            from io import StringIO
            for key, content in {
                "providers.yaml": PROVIDERS_YAML,
                "user_keys.yaml": USER_KEYS_YAML,
            }.items():
                if path.endswith(key):
                    sio = StringIO(content)
                    sio.__enter__ = lambda s: s
                    sio.__exit__ = lambda s, *a: None
                    return sio
            if path.endswith("models.yaml"):
                sio = StringIO("bad yaml")
                sio.__enter__ = lambda s: s
                sio.__exit__ = lambda s, *a: None
                return sio
            raise FileNotFoundError(path)

        with patch("builtins.open", side_effect=_open_with_bad_yaml), \
             patch("yaml.safe_load", side_effect=[
                 yaml.safe_load(PROVIDERS_YAML),
                 yaml.YAMLError("bad yaml"),
             ]), \
             patch("src.core.config_manager.logger"):
            with pytest.raises(RuntimeError, match="Failed to parse config"):
                cm._load_config(fail_on_error=True)


# ===================================================================
# reload_config
# ===================================================================

class TestReloadConfig:

    def test_invokes_callbacks_on_change(self):
        """reload_config invokes registered callbacks when config changes."""
        cm = _build_config_manager()
        callback = MagicMock()
        cm.add_reload_callback(callback)

        # Reload with full config
        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            cm.reload_config()

        callback.assert_called_once()

    def test_rejects_partial_config_keeps_previous(self):
        """Partial config is rejected; previous config is kept."""
        cm = _build_config_manager()
        original_config = cm.get_config().copy()
        callback = MagicMock()
        cm.add_reload_callback(callback)

        # Reload with only providers (missing models and user_keys)
        partial_map = {"providers.yaml": PROVIDERS_YAML}
        with patch("builtins.open", side_effect=_multi_open(partial_map)), \
             patch("src.core.config_manager.logger"):
            cm.reload_config()

        # Callback should NOT be invoked
        callback.assert_not_called()
        # Config should remain unchanged
        assert cm.get_config() == original_config


# ===================================================================
# Property getters (env-var backed)
# ===================================================================

class TestPropertyGetters:

    def test_httpx_max_connections_default(self):
        """httpx_max_connections returns default 100."""
        cm = _build_config_manager()
        with patch.dict("os.environ", {}, clear=True):
            assert cm.httpx_max_connections == 100

    def test_httpx_max_connections_from_env(self):
        """httpx_max_connections reads from env var."""
        cm = _build_config_manager()
        with patch.dict("os.environ", {"HTTPX_MAX_CONNECTIONS": "200"}, clear=True):
            assert cm.httpx_max_connections == 200

    def test_provider_max_retries_default(self):
        """provider_max_retries defaults to 3."""
        cm = _build_config_manager()
        with patch.dict("os.environ", {}, clear=True):
            assert cm.provider_max_retries == 3

    def test_provider_retry_base_delay_from_env(self):
        """provider_retry_base_delay reads env var as float."""
        cm = _build_config_manager()
        with patch.dict("os.environ", {"PROVIDER_RETRY_BASE_DELAY": "2.5"}, clear=True):
            assert cm.provider_retry_base_delay == 2.5

    def test_httpx_pool_timeout_default(self):
        """httpx_pool_timeout defaults to 5.0."""
        cm = _build_config_manager()
        with patch.dict("os.environ", {}, clear=True):
            assert cm.httpx_pool_timeout == 5.0

    def test_config_reload_interval_from_env(self):
        """config_reload_interval reads from env."""
        cm = _build_config_manager()
        with patch.dict("os.environ", {"CONFIG_RELOAD_INTERVAL": "10"}, clear=True):
            assert cm.config_reload_interval == 10


# ===================================================================
# should_sanitize_messages
# ===================================================================

class TestShouldSanitizeMessages:

    def test_default_false(self):
        """Default: sanitize_messages is False."""
        cm = _build_config_manager()
        assert cm.should_sanitize_messages is False

    def test_env_true(self):
        """SANITIZE_MESSAGES=true makes it True."""
        cm = _build_config_manager(env={"SANITIZE_MESSAGES": "true"})
        assert cm.should_sanitize_messages is True

    def test_env_false(self):
        """SANITIZE_MESSAGES=false keeps it False."""
        cm = _build_config_manager(env={"SANITIZE_MESSAGES": "false"})
        assert cm.should_sanitize_messages is False


# ===================================================================
# add_reload_callback
# ===================================================================

class TestAddReloadCallback:

    def test_callback_called_on_reload(self):
        """Registered callback is called on successful reload."""
        cm = _build_config_manager()
        cb = MagicMock()
        cm.add_reload_callback(cb)

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            cm.reload_config()

        cb.assert_called_once()

    def test_multiple_callbacks(self):
        """Multiple registered callbacks are all called."""
        cm = _build_config_manager()
        cb1 = MagicMock()
        cb2 = MagicMock()
        cm.add_reload_callback(cb1)
        cm.add_reload_callback(cb2)

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            cm.reload_config()

        cb1.assert_called_once()
        cb2.assert_called_once()
