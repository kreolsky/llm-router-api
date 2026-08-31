"""YAML-based configuration management with hot-reload support."""
# SYSTEM: config — YAML load, 5s hot reload, env-backed settings
import asyncio
import contextlib
import os
from dataclasses import dataclass, fields
from typing import Any

import yaml

from .logging import logger

# ---------------------------------------------------------------------------
# Env-backed settings
#
# ARCH: every env-backed setting is read ONCE, at construction, into a frozen
# Settings snapshot. Environment variables cannot change without restarting
# the process, so re-reading them per access bought nothing and cost the hot
# path a parse on every stream. Reading once also means a malformed value is
# caught at startup (fail fast, like the rest of the config) instead of
# raising inside a request.
#
# ARCH: the Settings field defaults are the SINGLE copy of the no-config
# fallbacks. Each field's env var is its upper-cased name (verified for every
# legacy var when the tuple form was collapsed) — adding a knob is adding a
# field, and there is no second map a drift test would have to pin.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Typed snapshot of every env-backed knob, resolved once at construction.

    Passed down the provider chain as a required argument; consumers never
    re-read the environment and never see a partially-applied knob.
    """

    # --- HTTPX pools (applied per provider pool; each provider owns its own) ---
    httpx_max_connections: int = 100
    httpx_max_keepalive_connections: int = 20
    httpx_connect_timeout: float = 60.0
    httpx_pool_timeout: float = 5.0
    # WHY: HTTPX_READ_TIMEOUT is only the client-default READ fallback —
    # every field _create_timeout leaves unspecified lands here; stream and
    # non-stream chat override it per call site with stream_read_timeout.
    httpx_read_timeout: float = 60.0
    # WHY: streaming can be long-lived; a separate read timeout keeps
    # non-stream requests snappy.
    stream_read_timeout: float = 300.0
    queue_wait_timeout: float = 30.0
    config_reload_interval: int = 5
    # --- provider retry (429 backoff) ---
    provider_max_retries: int = 3
    provider_retry_base_delay: float = 1.0
    provider_retry_max_delay: float = 30.0
    # --- per-call-site timeouts ---
    openai_connect_timeout: float = 60.0
    openai_transcription_timeout: float = 3600.0
    openai_embeddings_read_timeout: float = 30.0
    # --- model capabilities auto-cache (see src/core/model_capabilities/) ---
    model_cache_refresh_interval: int = 3600
    model_cache_enabled: bool = True
    model_cache_path: str = "data/model_cache.json"
    # --- misc ---
    default_stt_model: str = "stt/dummy"
    usage_db_path: str = "data/usage.db"
    # Optional key protecting the /stat/api/* JSON endpoints (X-Stat-Key
    # header). Empty (unset) keeps the stats API open as before.
    stat_api_key: str = ""


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
        self._post_swap_callbacks = []
        
        self.debug = _env_bool("DEBUG", False)
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.settings = self._read_env_settings()

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
        self._validate_models(config)
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

    @staticmethod
    def _validate_models(config: dict[str, Any]) -> None:
        """Soft-validate models.yaml: warn and DROP an invalid reasoning_effort block.

        Why soft: models.yaml is hot-reloaded every 5s; a hard raise there
        kills a running router on a typo. Dropping (not just warning) makes
        "ignore the whole block" real for every downstream consumer — the
        funnel and /v1/models never see a malformed block. A model carrying
        BOTH an options effort key and a reasoning_effort block gets the same
        verdict: options wins at merge time (providers/base.py
        _apply_model_config), so the block would advertise a policy the
        upstream never sees. A typo'd key drops the block too — a misspelled
        ``param`` would otherwise send the effort to the wrong wire location
        while /v1/models still advertised the policy.
        """
        # WHY function-level import: core must not import services at module
        # level (services import core); parse_effort_policy is the shared
        # single source of validity with the request-path enforcement.
        from ..services.reasoning_effort import parse_effort_policy

        models = config.get("models") or {}
        for model_id, model_cfg in models.items():
            if not isinstance(model_cfg, dict) or "reasoning_effort" not in model_cfg:
                continue
            _, reason = parse_effort_policy(model_cfg)
            if reason is not None:
                logger.warning(
                    f"models.yaml '{model_id}': ignoring reasoning_effort block — {reason}",
                    extra={"config": {"model": model_id}},
                )
                del model_cfg["reasoning_effort"]

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
    
    def _read_env_settings(self) -> Settings:
        """Resolve every Settings field from its upper-cased env var (see module header)."""
        values: dict[str, Any] = {}
        for f in fields(Settings):
            env_var = f.name.upper()
            if isinstance(f.default, bool):
                values[f.name] = _env_bool(env_var, f.default)
            elif isinstance(f.default, str):
                values[f.name] = os.getenv(env_var, f.default)
            else:
                values[f.name] = _env_number(env_var, f.default, type(f.default))
        return Settings(**values)

    def add_reload_callback(self, callback, name: str = ""):
        """Register an async callback invoked BEFORE the new config is published (pre-swap phase).

        callback signature: ``async def cb(new_config: dict) -> None``.
        Pre-swap callbacks can VETO the reload: on callback failure the swap
        is aborted and self.config keeps the previous value. Callbacks run
        sequentially. Use add_post_swap_callback for work that must observe
        the already-published config instead.
        """
        self._on_reload_callbacks.append((name, callback))

    def add_post_swap_callback(self, callback, name: str = ""):
        """Register an async callback invoked AFTER self.config is swapped (post-swap phase).

        callback signature: ``async def cb(new_config: dict) -> None``.
        Post-swap callbacks run once the new config is already published, so a
        failure can only be logged — there is nothing to roll back to. This is
        the phase that publishes derived caches (e.g. the provider cache) so
        they never re-populate from a config the swap is about to retire.
        """
        self._post_swap_callbacks.append((name, callback))

    async def reload_config(self) -> bool:
        """Reload config from disk in two phases.

        Phase 1 (pre-swap): every add_reload_callback runs with the freshly
        loaded new_config while self.config still holds the previous value. A
        raising callback ABORTS the reload: self.config is not swapped and
        False is returned — the previous config stays in place.

        Phase 2 (post-swap): self.config = new_config, then every
        add_post_swap_callback runs. A raising callback is logged and the
        swap STAYS published (there is nothing to roll back to), but the
        reload reports False — see Returns.

        Returns True only when the new config was applied AND every post-swap
        callback ran cleanly. False when it was rejected (incomplete on disk,
        or refused by a pre-swap callback) or a post-swap callback failed:
        the config stays published either way, but the on-disk state must not
        be treated as consumed — the caller leaves last_mtimes uncommitted so
        the next poll retries (see _poll_once).
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
            post_swap_failed = False
            for name, cb in self._post_swap_callbacks:
                try:
                    await cb(new_config)
                except Exception:
                    logger.error(
                        f"Post-swap config reload callback failed: {name or '(unnamed)'}",
                        extra={"config": {"operation": "reload_post_swap_error", "callback_name": name}},
                        exc_info=True,
                    )
                    post_swap_failed = True
            # INVARIANT: a reload whose post-swap callback failed never logs
            # the plain success line.
            # Why: the swap IS published but a derived cache (the provider
            # registry) is not, and the retry below reprints this line every
            # poll interval — an INFO "Configuration reloaded" repeating
            # forever is what an operator reads as "all good" while the
            # router serves a half-applied state.
            log = logger.warning if post_swap_failed else logger.info
            log(
                "Configuration reloaded, but a post-swap callback failed - retrying"
                if post_swap_failed else "Configuration reloaded",
                extra={
                    "config": {
                        "operation": "reload_complete",
                        "post_swap_failed": post_swap_failed,
                        "providers_count": len(self.config.get('providers', {})),
                        "models_count": len(self.config.get('models', {})),
                        "user_keys_count": len(self.config.get('user_keys', {}))
                    }
                })
            # WHY: True here would let _poll_once commit last_mtimes, and a
            # half-applied reload (the config swapped, a derived cache like
            # the provider registry not) would never be retried until the
            # file changed again — e.g. a provider added by this reload
            # would 404 in silence. False keeps the on-disk state
            # unconsumed so the next tick retries; with provider instance
            # reuse the retry re-stages cheaply. The retry repeats every
            # config_reload_interval until the callback succeeds or the
            # files change again — deliberate: a half-applied reload must
            # not go quiet, and the reuse path keeps each attempt cheap.
            return not post_swap_failed

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
        # success — and success means APPLIED CLEANLY, post-swap callbacks
        # included. Recording it up front means a config rejected by a
        # callback (a typo in providers.yaml) or half-applied by a failed
        # post-swap step is never retried until the file changes again, and
        # the router keeps serving the stale or half-new state in silence.
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

            await asyncio.sleep(self.settings.config_reload_interval)

    def start_reloader_task(self) -> asyncio.Task:
        return asyncio.create_task(self._reload_config_task())
