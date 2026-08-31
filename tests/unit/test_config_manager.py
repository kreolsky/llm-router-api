"""Unit tests for src/core/config_manager.py — ConfigManager class."""

from unittest.mock import AsyncMock, patch

import pytest
import yaml

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
             patch("src.core.config_manager.logger"), pytest.raises(RuntimeError, match="Failed to parse config"):
            cm._load_config(fail_on_error=True)


# ===================================================================
# Top-level key validation
# ===================================================================

class TestTopLevelKeyValidation:

    def test_flat_yaml_without_wrapper_raises(self):
        """A flat providers.yaml (no top-level 'providers:' key) raises RuntimeError."""
        # Missing the 'providers:' wrapper — just a mapping of provider entries
        flat_providers = (
            "openai:\n  type: openai\n  base_url: https://api.openai.com\n"
        )
        file_map = {
            "providers.yaml": flat_providers,
            "models.yaml": MODELS_YAML,
            "user_keys.yaml": USER_KEYS_YAML,
        }
        with patch("builtins.open", side_effect=_multi_open(file_map)), \
             patch("os.path.exists", return_value=True), \
             patch("os.path.getmtime", return_value=1000.0), \
             patch("src.core.config_manager.logger"):
            with pytest.raises(RuntimeError, match="missing top-level 'providers:'"):
                ConfigManager(config_dir="/fake/config")

    def test_flat_yaml_at_reload_warns_skips(self):
        """At reload (fail_on_error=False) a malformed file is skipped, others load."""
        flat_models = "gpt-4:\n  provider: openai\n"
        file_map = {
            "providers.yaml": PROVIDERS_YAML,
            "models.yaml": flat_models,
            "user_keys.yaml": USER_KEYS_YAML,
        }
        cm = _build_config_manager()
        with patch("builtins.open", side_effect=_multi_open(file_map)), \
             patch("src.core.config_manager.logger"):
            config = cm._load_config(fail_on_error=False)
        assert "providers" in config
        assert "user_keys" in config
        # models.yaml had no top-level 'models:' → skipped
        assert "models" not in config


# ===================================================================
# reload_config
# ===================================================================

class TestReloadConfig:

    @pytest.mark.asyncio
    async def test_invokes_callbacks_on_change(self):
        """reload_config invokes registered callbacks when config changes."""
        cm = _build_config_manager()
        callback = AsyncMock()
        cm.add_reload_callback(callback, name="test_cb")

        # Reload with full config
        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            await cm.reload_config()

        cm_full_config = cm.get_config()
        callback.assert_awaited_once_with(cm_full_config)

    @pytest.mark.asyncio
    async def test_rejects_partial_config_keeps_previous(self):
        """Partial config is rejected; previous config is kept."""
        cm = _build_config_manager()
        original_config = cm.get_config().copy()
        callback = AsyncMock()
        cm.add_reload_callback(callback, name="test_cb")

        # Reload with only providers (missing models and user_keys)
        partial_map = {"providers.yaml": PROVIDERS_YAML}
        with patch("builtins.open", side_effect=_multi_open(partial_map)), \
             patch("src.core.config_manager.logger"):
            await cm.reload_config()

        # Callback should NOT be invoked
        callback.assert_not_called()
        # Config should remain unchanged
        assert cm.get_config() == original_config

    @pytest.mark.asyncio
    async def test_callback_failure_keeps_previous_config(self):
        """When a callback raises, self.config is NOT swapped (old config retained)."""
        cm = _build_config_manager()
        original_config = cm.get_config().copy()
        failing_cb = AsyncMock(side_effect=RuntimeError("boom"))
        cm.add_reload_callback(failing_cb, name="failing")

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            await cm.reload_config()

        failing_cb.assert_awaited_once()
        assert cm.get_config() == original_config  # old config retained


# ===================================================================
# Typed Settings snapshot
# ===================================================================

class TestSettings:
    """ConfigManager exposes a frozen, typed Settings built once at construction."""

    def _cm_with_env(self, env):
        with patch.dict("os.environ", env, clear=True):
            return _build_config_manager()

    def test_settings_object_exposed(self):
        """cm.settings is a Settings carrying the resolved env values."""
        from src.core.config_manager import Settings
        cm = self._cm_with_env({"QUEUE_WAIT_TIMEOUT": "7.5"})
        assert isinstance(cm.settings, Settings)
        assert cm.settings.queue_wait_timeout == 7.5

    def test_settings_defaults(self):
        """A bare Settings() carries the documented no-config defaults."""
        from src.core.config_manager import Settings
        s = Settings()
        assert s.queue_wait_timeout == 30.0
        assert s.stream_read_timeout == 300.0
        assert s.provider_max_retries == 3
        assert s.provider_retry_base_delay == 1.0
        assert s.provider_retry_max_delay == 30.0
        assert s.openai_connect_timeout == 60.0
        assert s.openai_transcription_timeout == 3600.0
        assert s.openai_embeddings_read_timeout == 30.0
        assert s.httpx_max_connections == 100
        assert s.default_stt_model == "stt/dummy"

    def test_settings_is_frozen(self):
        """Settings is frozen — a running process cannot mutate its knobs."""
        from dataclasses import FrozenInstanceError

        from src.core.config_manager import Settings
        s = Settings()
        with pytest.raises(FrozenInstanceError):
            s.queue_wait_timeout = 1.0

    def test_no_duck_typed_attribute_access(self):
        """Env-backed knobs are NOT attributes of ConfigManager anymore —
        only cm.settings.<name> resolves; the bare name is an AttributeError."""
        cm = _build_config_manager()
        assert cm.settings.stream_read_timeout == 300.0
        with pytest.raises(AttributeError):
            cm.stream_read_timeout

    def test_env_resolved_once_into_settings(self):
        """Settings is resolved at construction; a later env change is ignored."""
        with patch.dict("os.environ", {"STREAM_READ_TIMEOUT": "111"}, clear=True):
            cm = _build_config_manager()
        with patch.dict("os.environ", {"STREAM_READ_TIMEOUT": "999"}, clear=True):
            assert cm.settings.stream_read_timeout == 111.0

    def test_malformed_env_falls_back_to_default(self):
        """An unparsable numeric env var degrades to the Settings default."""
        with patch.dict("os.environ", {"QUEUE_WAIT_TIMEOUT": "not-a-number"}, clear=True):
            cm = _build_config_manager()
        assert cm.settings.queue_wait_timeout == 30.0


class TestPropertyGetters:
    """Env-backed settings are resolved once, when the ConfigManager is built."""

    def _cm_with_env(self, env):
        with patch.dict("os.environ", env, clear=True):
            return _build_config_manager()

    def test_httpx_max_connections_default(self):
        """httpx_max_connections returns default 100."""
        assert self._cm_with_env({}).settings.httpx_max_connections == 100

    def test_httpx_max_connections_from_env(self):
        """httpx_max_connections reads from env var."""
        assert self._cm_with_env({"HTTPX_MAX_CONNECTIONS": "200"}).settings.httpx_max_connections == 200

    def test_provider_max_retries_default(self):
        """provider_max_retries defaults to 3."""
        assert self._cm_with_env({}).settings.provider_max_retries == 3

    def test_provider_retry_base_delay_from_env(self):
        """provider_retry_base_delay reads env var as float."""
        assert self._cm_with_env({"PROVIDER_RETRY_BASE_DELAY": "2.5"}).settings.provider_retry_base_delay == 2.5

    def test_httpx_pool_timeout_default(self):
        """httpx_pool_timeout defaults to 5.0."""
        assert self._cm_with_env({}).settings.httpx_pool_timeout == 5.0

    def test_config_reload_interval_from_env(self):
        """config_reload_interval reads from env."""
        assert self._cm_with_env({"CONFIG_RELOAD_INTERVAL": "10"}).settings.config_reload_interval == 10

    def test_stream_read_timeout_default(self):
        """stream_read_timeout defaults to 300.0."""
        assert self._cm_with_env({}).settings.stream_read_timeout == 300.0

    def test_stream_read_timeout_from_env(self):
        """stream_read_timeout reads from env as float."""
        assert self._cm_with_env({"STREAM_READ_TIMEOUT": "600"}).settings.stream_read_timeout == 600.0

    def test_default_stt_model_default(self):
        """default_stt_model defaults to stt/dummy."""
        assert self._cm_with_env({}).settings.default_stt_model == "stt/dummy"

    def test_default_stt_model_from_env(self):
        """default_stt_model reads from env."""
        assert self._cm_with_env({"DEFAULT_STT_MODEL": "stt/custom"}).settings.default_stt_model == "stt/custom"

    def test_model_cache_settings(self):
        """Model-cache settings resolve from env with the documented defaults."""
        cm = self._cm_with_env({})
        assert cm.settings.model_cache_enabled is True
        assert cm.settings.model_cache_refresh_interval == 3600
        assert cm.settings.model_cache_path == "data/model_cache.json"

        cm = self._cm_with_env({"MODEL_CACHE_ENABLED": "false", "MODEL_CACHE_PATH": "/tmp/c.json"})
        assert cm.settings.model_cache_enabled is False
        assert cm.settings.model_cache_path == "/tmp/c.json"

    def test_model_cache_ttl_is_gone(self):
        """MODEL_CACHE_TTL was a dead knob (stale-if-error contradicts a TTL) — removed."""
        with pytest.raises(AttributeError):
            self._cm_with_env({"MODEL_CACHE_TTL": "1"}).settings.model_cache_ttl

    def test_usage_db_path_settings(self):
        """usage_db_path resolves from env with the documented default."""
        cm = self._cm_with_env({})
        assert cm.settings.usage_db_path == "data/usage.db"

        cm = self._cm_with_env({"USAGE_DB_PATH": "/tmp/usage.db"})
        assert cm.settings.usage_db_path == "/tmp/usage.db"


class TestEnvSettingsResolvedOnce:
    """Values are frozen at construction and malformed input degrades gracefully."""

    def test_later_env_change_is_ignored(self):
        """Changing the env after construction does not change a resolved setting."""
        with patch.dict("os.environ", {"STREAM_READ_TIMEOUT": "111"}, clear=True):
            cm = _build_config_manager()
        with patch.dict("os.environ", {"STREAM_READ_TIMEOUT": "999"}, clear=True):
            assert cm.settings.stream_read_timeout == 111.0

    def test_malformed_number_falls_back_to_default(self):
        """An unparsable numeric env var falls back rather than crashing a request."""
        with patch.dict("os.environ", {"QUEUE_WAIT_TIMEOUT": "not-a-number"}, clear=True):
            cm = _build_config_manager()
        assert cm.settings.queue_wait_timeout == 30.0

    def test_unknown_attribute_still_raises(self):
        """Only cm.settings exists; anything else is a normal AttributeError."""
        cm = _build_config_manager()
        with pytest.raises(AttributeError):
            cm.definitely_not_a_setting


# ===================================================================
# _assert_config_complete (fail-fast validation)
# ===================================================================

class TestAssertConfigComplete:

    def test_empty_section_raises(self):
        """Empty providers section raises RuntimeError (fail-fast)."""
        from src.core.config_manager import ConfigManager
        with pytest.raises(RuntimeError, match="missing or empty"):
            ConfigManager._assert_config_complete({"providers": {}, "models": {"m": {}}, "user_keys": {"k": {}}})

    def test_missing_section_raises(self):
        """Missing user_keys section raises RuntimeError."""
        from src.core.config_manager import ConfigManager
        with pytest.raises(RuntimeError, match="user_keys"):
            ConfigManager._assert_config_complete({"providers": {"p": {}}, "models": {"m": {}}})

    def test_complete_config_passes(self):
        """All three non-empty sections pass validation."""
        from src.core.config_manager import ConfigManager
        ConfigManager._assert_config_complete(
            {"providers": {"p": {}}, "models": {"m": {}}, "user_keys": {"k": {}}}
        )


# ===================================================================
# add_reload_callback
# ===================================================================

class TestAddReloadCallback:

    @pytest.mark.asyncio
    async def test_callback_called_on_reload(self):
        """Registered callback is called on successful reload."""
        cm = _build_config_manager()
        cb = AsyncMock()
        cm.add_reload_callback(cb, name="cb")

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            await cm.reload_config()

        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_callbacks(self):
        """Multiple registered callbacks are all called."""
        cm = _build_config_manager()
        cb1 = AsyncMock()
        cb2 = AsyncMock()
        cm.add_reload_callback(cb1, name="cb1")
        cm.add_reload_callback(cb2, name="cb2")

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            await cm.reload_config()

        cb1.assert_awaited_once()
        cb2.assert_awaited_once()


# ===================================================================
# add_post_swap_callback (two-phase reload)
# ===================================================================

class TestAddPostSwapCallback:
    """Post-swap callbacks run AFTER self.config is swapped and cannot abort it."""

    MODELS_V2 = "models:\n  gpt-4:\n    provider: openai\n  gpt-5:\n    provider: openai\n"

    @pytest.mark.asyncio
    async def test_runs_after_config_swap(self):
        """Inside a post-swap callback get_config() already returns the NEW
        config; inside a pre-swap callback it still returns the old one."""
        cm = _build_config_manager()
        seen = {}

        async def pre_cb(new_config):
            seen["pre"] = "gpt-5" in cm.get_config().get("models", {})

        async def post_cb(new_config):
            seen["post"] = "gpt-5" in cm.get_config().get("models", {})

        cm.add_reload_callback(pre_cb, name="pre")
        cm.add_post_swap_callback(post_cb, name="post")

        file_map = {
            "providers.yaml": PROVIDERS_YAML,
            "models.yaml": self.MODELS_V2,
            "user_keys.yaml": USER_KEYS_YAML,
        }
        with patch("builtins.open", side_effect=_multi_open(file_map)), \
             patch("src.core.config_manager.logger"):
            assert await cm.reload_config() is True

        assert seen == {"pre": False, "post": True}

    @pytest.mark.asyncio
    async def test_post_swap_failure_returns_false_but_keeps_new_config(self):
        """A failing post-swap callback cannot un-publish the swap: the config
        is already live and there is nothing to roll back to. The reload still
        reports False so _poll_once does not treat the on-disk state as
        consumed — the next tick retries the reload (cheap with provider
        instance reuse)."""
        cm = _build_config_manager()
        failing = AsyncMock(side_effect=RuntimeError("boom"))
        cm.add_post_swap_callback(failing, name="failing_post")

        file_map = {
            "providers.yaml": PROVIDERS_YAML,
            "models.yaml": self.MODELS_V2,
            "user_keys.yaml": USER_KEYS_YAML,
        }
        with patch("builtins.open", side_effect=_multi_open(file_map)), \
             patch("src.core.config_manager.logger"):
            assert await cm.reload_config() is False

        failing.assert_awaited_once()
        # The swap itself stays published.
        assert "gpt-5" in cm.get_config().get("models", {})

    @pytest.mark.asyncio
    async def test_post_swap_failure_never_logs_the_plain_success_line(self):
        """The reload_complete line is a WARNING carrying post_swap_failed=True
        when a post-swap callback raised. The retry loop reprints this line
        every poll interval, so an INFO 'Configuration reloaded' would read as
        'all good' forever while the router serves a half-applied state."""
        cm = _build_config_manager()
        cm.add_post_swap_callback(AsyncMock(side_effect=RuntimeError("boom")), name="failing_post")

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger") as mock_logger:
            assert await cm.reload_config() is False

        completions = [
            call for call in mock_logger.warning.call_args_list
            if call.kwargs.get("extra", {}).get("config", {}).get("operation") == "reload_complete"
        ]
        assert len(completions) == 1, "the completion line must be logged once, at warning"
        assert completions[0].kwargs["extra"]["config"]["post_swap_failed"] is True
        # And never as the plain success line.
        assert not [
            call for call in mock_logger.info.call_args_list
            if call.kwargs.get("extra", {}).get("config", {}).get("operation") == "reload_complete"
        ]

    @pytest.mark.asyncio
    async def test_clean_reload_logs_the_success_line_at_info(self):
        """The failing branch above is only meaningful if the clean path still
        logs reload_complete at INFO with the flag false."""
        cm = _build_config_manager()
        cm.add_post_swap_callback(AsyncMock(), name="fine_post")

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger") as mock_logger:
            assert await cm.reload_config() is True

        completions = [
            call for call in mock_logger.info.call_args_list
            if call.kwargs.get("extra", {}).get("config", {}).get("operation") == "reload_complete"
        ]
        assert len(completions) == 1
        assert completions[0].kwargs["extra"]["config"]["post_swap_failed"] is False
        assert not mock_logger.warning.call_args_list

    @pytest.mark.asyncio
    async def test_pre_swap_failure_skips_post_swap(self):
        """A pre-swap (aborting) callback failure prevents the swap AND the
        post-swap callbacks from running at all."""
        cm = _build_config_manager()
        original_config = cm.get_config().copy()
        post = AsyncMock()
        cm.add_reload_callback(AsyncMock(side_effect=RuntimeError("boom")), name="failing_pre")
        cm.add_post_swap_callback(post, name="post")

        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            assert await cm.reload_config() is False

        post.assert_not_called()
        assert cm.get_config() == original_config


# ===================================================================
# mtime bookkeeping: a rejected reload must be retried
# ===================================================================

class TestReloadRetriesAfterFailure:
    """The watcher must not treat a REJECTED reload as applied.

    Recording the new mtimes before knowing whether the reload succeeded means a
    config rejected by a callback (e.g. a typo in providers.yaml) is never retried
    until the file changes again — the router silently keeps serving stale config.
    """

    @pytest.mark.asyncio
    async def test_reload_config_reports_success(self):
        """reload_config returns True when the new config is applied."""
        cm = _build_config_manager()
        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            assert await cm.reload_config() is True

    @pytest.mark.asyncio
    async def test_reload_config_reports_callback_failure(self):
        """reload_config returns False when a callback rejects the new config."""
        cm = _build_config_manager()
        cm.add_reload_callback(AsyncMock(side_effect=RuntimeError("boom")), name="failing")
        with patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            assert await cm.reload_config() is False

    @pytest.mark.asyncio
    async def test_reload_config_reports_partial_rejection(self):
        """reload_config returns False when the loaded config is incomplete."""
        cm = _build_config_manager()
        with patch("builtins.open", side_effect=_multi_open({"providers.yaml": PROVIDERS_YAML})), \
             patch("src.core.config_manager.logger"):
            assert await cm.reload_config() is False

    @pytest.mark.asyncio
    async def test_failed_reload_leaves_mtimes_unchanged(self):
        """After a rejected reload the recorded mtimes still allow a retry."""
        cm = _build_config_manager()
        before = dict(cm.last_mtimes)
        cm.add_reload_callback(AsyncMock(side_effect=RuntimeError("boom")), name="failing")

        with patch("os.path.getmtime", return_value=2000.0), \
             patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            assert await cm._poll_once() is True   # change detected, reload attempted
            assert await cm._poll_once() is True   # still pending: retried

        assert cm.last_mtimes == before

    @pytest.mark.asyncio
    async def test_post_swap_failure_leaves_mtimes_uncommitted(self):
        """A post-swap failure is not 'applied': last_mtimes stay uncommitted
        so the next _poll_once retries the reload. Without this, a provider
        added by a reload whose publish callback failed would 404 until the
        file was touched again — the config swap kept, the cache half-applied,
        nothing retried."""
        cm = _build_config_manager()
        before = dict(cm.last_mtimes)
        cm.add_post_swap_callback(AsyncMock(side_effect=RuntimeError("boom")), name="failing_post")

        with patch("os.path.getmtime", return_value=2000.0), \
             patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            assert await cm._poll_once() is True   # change detected, reload attempted
            assert await cm._poll_once() is True   # still pending: retried

        assert cm.last_mtimes == before

    @pytest.mark.asyncio
    async def test_successful_reload_commits_mtimes(self):
        """A successful reload records the new mtimes so it is not repeated."""
        cm = _build_config_manager()

        with patch("os.path.getmtime", return_value=2000.0), \
             patch("builtins.open", side_effect=_multi_open(ALL_YAMLS)), \
             patch("src.core.config_manager.logger"):
            assert await cm._poll_once() is True    # change detected and applied
            assert await cm._poll_once() is False   # nothing left to do

        assert set(cm.last_mtimes.values()) == {2000.0}
