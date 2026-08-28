"""YAML-based configuration management with hot-reload support."""
# SYSTEM: config — YAML load, 5s hot reload, env-backed settings
import asyncio
import contextlib
import os
from typing import Any

import yaml

from .logging import logger

# ---------------------------------------------------------------------------
# Env-backed settings
#
# ARCH: every env-backed setting is read ONCE, at construction. Environment
# variables cannot change without restarting the process, so re-reading them per
# access bought nothing and cost the hot path a parse on every stream. Reading
# once also means a malformed value is caught at startup (fail fast, like the
# rest of the config) instead of raising inside a request.
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() == "true"


def _env_number(name: str, default, cast):
    """Read a numeric env var, falling back to default with a warning if unparsable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except (ValueError, TypeError):
        logger.warning(
            f"{name} has invalid value {raw!r}, falling back to default {default}",
            extra={"config": {"setting": name, "raw_value": raw}},
        )
        return default


class ConfigManager:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.providers_path = os.path.join(config_dir, "providers.yaml")
        self.models_path = os.path.join(config_dir, "models.yaml")
        self.user_keys_path = os.path.join(config_dir, "user_keys.yaml")
        self.model_info_path = os.path.join(config_dir, "model_info.yaml")
        self.config = self._load_config(fail_on_error=True)
        self._assert_config_complete(self.config)
        self.last_mtimes = {} # Initialize last_mtimes as instance variable
        self._initialize_mtimes()
        self._on_reload_callbacks = []
        
        self.debug = _env_bool("DEBUG", False)
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self._settings = self._read_env_settings()

        # Log configuration initialization
        logger.info("Configuration manager initialized", extra={
            "config": {
                "config_dir": config_dir,
                "debug_enabled": self.debug,
                "log_level": self.log_level,
                "providers_config_exists": os.path.exists(self.providers_path),
                "models_config_exists": os.path.exists(self.models_path),
                "user_keys_config_exists": os.path.exists(self.user_keys_path),
                "model_info_config_exists": os.path.exists(self.model_info_path)
            }
        })

    def _load_config(self, fail_on_error: bool = False) -> dict[str, Any]:
        """Load and merge all YAML config files."""
        config = {}
        file_map = [
            (self.providers_path, 'providers', True),
            (self.models_path, 'models', True),
            (self.user_keys_path, 'user_keys', True),
            (self.model_info_path, 'model_info', False),
        ]
        for path, key, required in file_map:
            try:
                with open(path) as f:
                    loaded = yaml.safe_load(f) or {}
                # WHY: a flat YAML (missing the top-level wrapper key) would silently
                # coerce to {} and only fail later at startup assert (and not at reload).
                if not isinstance(loaded, dict) or key not in loaded:
                    if fail_on_error and required:
                        raise RuntimeError(
                            f"Config file {path} missing top-level '{key}:' section"
                        )
                    logger.warning(f"Config file {path} missing top-level '{key}:' section")
                    continue
                config[key] = loaded[key] or {}
            except FileNotFoundError as e:
                logger.error(f"Configuration file not found: {path}")
                if fail_on_error and required:
                    raise RuntimeError(f"Critical config file missing: {path}") from e
            except yaml.YAMLError as e:
                logger.error(f"Error parsing YAML file {path}: {e}", exc_info=True)
                if fail_on_error and required:
                    raise RuntimeError(f"Failed to parse config: {path}") from e
        self._validate_model_info(config)
        return config

    # Allowed top-level keys per model_info entry (normalized schema; see
    # config/model_info.yaml header). Used by the soft validation below.
    _MODEL_INFO_KEYS = {
        "name", "description", "context_length", "max_completion_tokens",
        "is_moderated", "architecture", "supported_parameters", "reasoning", "pricing",
    }
    _MODEL_INFO_ARCH_KEYS = {
        "input_modalities", "output_modalities", "tokenizer", "instruct_type",
    }

    @staticmethod
    def _validate_model_info(config: dict[str, Any]) -> None:
        """Soft-validate model_info: warn on unknown keys and orphan entries.

        Non-fatal (model_info is required=False). Warns when an entry has no
        matching model in models.yaml, or uses keys outside the normalized
        schema — both indicate a stale or mistyped catalog.
        """
        model_info = config.get("model_info") or {}
        if not isinstance(model_info, dict) or not model_info:
            return
        models = config.get("models") or {}
        for model_id, entry in model_info.items():
            if not isinstance(entry, dict):
                logger.warning(
                    f"model_info entry '{model_id}' is not a mapping, ignoring",
                    extra={"config": {"model_info_key": model_id}},
                )
                continue
            if model_id not in models:
                logger.warning(
                    f"model_info entry '{model_id}' has no matching model in models.yaml",
                    extra={"config": {"model_info_key": model_id}},
                )
            unknown = set(entry) - ConfigManager._MODEL_INFO_KEYS
            if unknown:
                logger.warning(
                    f"model_info entry '{model_id}' has unknown keys: {sorted(unknown)}",
                    extra={"config": {"model_info_key": model_id, "unknown_keys": sorted(unknown)}},
                )
            arch = entry.get("architecture")
            if isinstance(arch, dict):
                arch_unknown = set(arch) - ConfigManager._MODEL_INFO_ARCH_KEYS
                if arch_unknown:
                    logger.warning(
                        f"model_info entry '{model_id}'.architecture has unknown keys: {sorted(arch_unknown)}",
                        extra={"config": {"model_info_key": model_id, "unknown_keys": sorted(arch_unknown)}},
                    )

    def get_config(self) -> dict[str, Any]:
        return self.config

    @staticmethod
    def _assert_config_complete(config: dict[str, Any]) -> None:
        """Fail-fast: every config section must be present and non-empty."""
        for section in ("providers", "models", "user_keys"):
            if not config.get(section):
                raise RuntimeError(
                    f"Configuration section '{section}' is missing or empty. "
                    f"Refusing to start."
                )
    
    _ENV_SETTINGS = (
        # (attribute, env var, default, cast)
        ("httpx_max_connections", "HTTPX_MAX_CONNECTIONS", 100, int),
        ("httpx_max_keepalive_connections", "HTTPX_MAX_KEEPALIVE_CONNECTIONS", 20, int),
        ("httpx_connect_timeout", "HTTPX_CONNECT_TIMEOUT", 60.0, float),
        ("httpx_pool_timeout", "HTTPX_POOL_TIMEOUT", 5.0, float),
        # WHY: HTTPX_READ_TIMEOUT is only the client-default READ fallback —
        # every field _create_timeout leaves unspecified lands here; stream and
        # non-stream chat override it per call site with stream_read_timeout.
        ("httpx_read_timeout", "HTTPX_READ_TIMEOUT", 60.0, float),
        # WHY: streaming can be long-lived; a separate read timeout keeps non-stream requests snappy
        ("stream_read_timeout", "STREAM_READ_TIMEOUT", 300.0, float),
        ("queue_wait_timeout", "QUEUE_WAIT_TIMEOUT", 30.0, float),
        ("config_reload_interval", "CONFIG_RELOAD_INTERVAL", 5, int),
        ("provider_max_retries", "PROVIDER_MAX_RETRIES", 3, int),
        ("provider_retry_base_delay", "PROVIDER_RETRY_BASE_DELAY", 1.0, float),
        ("provider_retry_max_delay", "PROVIDER_RETRY_MAX_DELAY", 30.0, float),
        ("openai_connect_timeout", "OPENAI_CONNECT_TIMEOUT", 60.0, float),
        ("openai_transcription_timeout", "OPENAI_TRANSCRIPTION_TIMEOUT", 3600.0, float),
        ("openai_embeddings_read_timeout", "OPENAI_EMBEDDINGS_READ_TIMEOUT", 30.0, float),
        # Model capabilities auto-cache (see src/core/model_capabilities.py)
        ("model_cache_refresh_interval", "MODEL_CACHE_REFRESH_INTERVAL", 3600, int),
        ("model_cache_ttl", "MODEL_CACHE_TTL", 86400, int),
    )

    def _read_env_settings(self) -> dict[str, Any]:
        """Resolve every env-backed setting once (see the module header)."""
        settings: dict[str, Any] = {
            name: _env_number(env_var, default, cast)
            for name, env_var, default, cast in self._ENV_SETTINGS
        }
        settings["default_stt_model"] = os.getenv("DEFAULT_STT_MODEL", "stt/dummy")
        settings["model_cache_enabled"] = _env_bool("MODEL_CACHE_ENABLED", True)
        settings["model_cache_path"] = os.getenv("MODEL_CACHE_PATH", "data/model_cache.json")
        settings["usage_db_path"] = os.getenv("USAGE_DB_PATH", "data/usage.db")
        # Optional key protecting the /stat/api/* JSON endpoints (X-Stat-Key
        # header). Empty (unset) keeps the stats API open as before.
        settings["stat_api_key"] = os.getenv("STAT_API_KEY", "")
        return settings

    def __getattr__(self, name: str) -> Any:
        """Expose env-backed settings as read-only attributes.

        Only reached for attributes not found normally, so it never shadows real
        state. Keeps every call site (config_manager.stream_read_timeout, ...)
        unchanged while the values themselves are resolved once at construction.
        """
        try:
            return self.__dict__["_settings"][name]
        except KeyError:
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            ) from None

    def add_reload_callback(self, callback, name: str = ""):
        """Register an async callback invoked after a successful config load.

        callback signature: ``async def cb(new_config: dict) -> None``.
        On callback failure reload is aborted and self.config is NOT swapped
        (the previous config stays in place). Callbacks run sequentially.
        """
        self._on_reload_callbacks.append((name, callback))

    async def reload_config(self) -> bool:
        """Reload config from disk and invoke registered async callbacks.

        Atomicity: self.config is swapped only AFTER every callback succeeds.
        If any callback raises, the previous config is retained (return, no swap).
        Each callback receives the freshly loaded new_config dict.

        Returns True when the new config was applied, False when it was rejected
        (incomplete on disk, or refused by a callback). The caller uses this to
        decide whether the on-disk state has been consumed — see _poll_once.
        """
        logger.info("Reloading configuration", extra={
            "config": {
                "operation": "reload_config",
                "config_dir": self.config_dir
            }
        })
        new_config = self._load_config(fail_on_error=False)
        if new_config.get('providers') and new_config.get('models') and new_config.get('user_keys'):
            for name, cb in self._on_reload_callbacks:
                try:
                    await cb(new_config)
                except Exception:
                    logger.error(
                        f"Config reload callback failed: {name or '(unnamed)'}",
                        extra={"config": {"operation": "reload_callback_error", "callback_name": name}},
                        exc_info=True,
                    )
                    return False
            self.config = new_config
            logger.info("Configuration reloaded", extra={
                "config": {
                    "operation": "reload_complete",
                    "providers_count": len(self.config.get('providers', {})),
                    "models_count": len(self.config.get('models', {})),
                    "user_keys_count": len(self.config.get('user_keys', {}))
                }
            })
            return True

        logger.warning("Partial config reload rejected, keeping previous config")
        return False

    @property
    def _watched_files(self) -> list:
        return [
            self.providers_path,
            self.models_path,
            self.user_keys_path,
            self.model_info_path,
        ]

    def _current_mtimes(self) -> dict[str, float]:
        """Read mtimes of the watched files, skipping the ones that are absent."""
        mtimes = {}
        for fpath in self._watched_files:
            with contextlib.suppress(FileNotFoundError):
                mtimes[fpath] = os.path.getmtime(fpath)
        return mtimes

    def _initialize_mtimes(self):
        self.last_mtimes = self._current_mtimes()

    async def _poll_once(self) -> bool:
        """One watcher iteration: reload if any watched file changed.

        Returns True when a change was detected (whether or not the reload was
        accepted), so callers/tests can distinguish "nothing to do" from "work
        attempted".

        # WHY: last_mtimes is committed only after reload_config() reports
        # success. Recording it up front means a config rejected by a callback
        # (a typo in providers.yaml) is never retried until the file changes
        # again, and the router keeps serving the stale config in silence.
        """
        mtimes = self._current_mtimes()
        changed_files = [
            fpath for fpath, mtime in mtimes.items()
            if fpath not in self.last_mtimes or self.last_mtimes[fpath] < mtime
        ]
        if not changed_files:
            return False

        logger.debug("Configuration files changed, triggering reload", extra={
            "config": {
                "operation": "auto_reload",
                "changed_files": changed_files,
            }
        })
        if await self.reload_config():
            self.last_mtimes = mtimes
        return True

    async def _reload_config_task(self):
        """Background task polling config files for mtime changes."""
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                logger.info("Config reload task cancelled")
                return
            except Exception as e:
                logger.error(f"Config reload task error: {e}", exc_info=True)

            await asyncio.sleep(self.config_reload_interval)

    def start_reloader_task(self) -> asyncio.Task:
        return asyncio.create_task(self._reload_config_task())
