"""YAML-based configuration management with hot-reload support."""
import yaml
import os
import asyncio
from typing import Dict, Any
from .logging import logger

class ConfigManager:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.providers_path = os.path.join(config_dir, "providers.yaml")
        self.models_path = os.path.join(config_dir, "models.yaml")
        self.user_keys_path = os.path.join(config_dir, "user_keys.yaml")
        self.config = self._load_config(fail_on_error=True)
        self.last_mtimes = {} # Initialize last_mtimes as instance variable
        self._initialize_mtimes()
        self._on_reload_callbacks = []
        
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.sanitize_messages = os.getenv("SANITIZE_MESSAGES", "false").lower() == "true"
        
        # Log configuration initialization
        logger.info("Configuration manager initialized", extra={
            "config": {
                "config_dir": config_dir,
                "debug_enabled": self.debug,
                "log_level": self.log_level,
                "sanitize_messages": self.sanitize_messages,
                "providers_config_exists": os.path.exists(self.providers_path),
                "models_config_exists": os.path.exists(self.models_path),
                "user_keys_config_exists": os.path.exists(self.user_keys_path)
            }
        })

    def _load_config(self, fail_on_error: bool = False) -> Dict[str, Any]:
        """Load and merge all YAML config files."""
        config = {}
        file_map = [
            (self.providers_path, 'providers'),
            (self.models_path, 'models'),
            (self.user_keys_path, 'user_keys'),
        ]
        for path, key in file_map:
            try:
                with open(path, 'r') as f:
                    config[key] = yaml.safe_load(f).get(key, {})
            except FileNotFoundError as e:
                logger.error(f"Configuration file not found: {path}")
                if fail_on_error:
                    raise RuntimeError(f"Critical config file missing: {path}") from e
            except yaml.YAMLError as e:
                logger.error(f"Error parsing YAML file {path}: {e}", exc_info=True)
                if fail_on_error:
                    raise RuntimeError(f"Failed to parse config: {path}") from e
        return config

    def get_config(self) -> Dict[str, Any]:
        return self.config
    
    @property
    def is_debug_enabled(self) -> bool:
        return self.debug

    @property
    def should_sanitize_messages(self) -> bool:
        return self.sanitize_messages

    @property
    def httpx_max_connections(self) -> int:
        return int(os.getenv("HTTPX_MAX_CONNECTIONS", "100"))

    @property
    def httpx_max_keepalive_connections(self) -> int:
        return int(os.getenv("HTTPX_MAX_KEEPALIVE_CONNECTIONS", "20"))

    @property
    def httpx_connect_timeout(self) -> float:
        return float(os.getenv("HTTPX_CONNECT_TIMEOUT", "60.0"))

    @property
    def httpx_pool_timeout(self) -> float:
        return float(os.getenv("HTTPX_POOL_TIMEOUT", "5.0"))

    @property
    def httpx_read_timeout(self) -> float:
        # WHY: without a read timeout, requests hang indefinitely when providers are unreachable
        return float(os.getenv("HTTPX_READ_TIMEOUT", "60.0"))

    @property
    def api_workers(self) -> int:
        return int(os.getenv("API_WORKERS", "4"))

    @property
    def config_reload_interval(self) -> int:
        return int(os.getenv("CONFIG_RELOAD_INTERVAL", "5"))

    @property
    def provider_max_retries(self) -> int:
        return int(os.getenv("PROVIDER_MAX_RETRIES", "3"))

    @property
    def provider_retry_base_delay(self) -> float:
        return float(os.getenv("PROVIDER_RETRY_BASE_DELAY", "1.0"))

    @property
    def provider_retry_max_delay(self) -> float:
        return float(os.getenv("PROVIDER_RETRY_MAX_DELAY", "30.0"))

    @property
    def openai_connect_timeout(self) -> float:
        return float(os.getenv("OPENAI_CONNECT_TIMEOUT", "60.0"))

    @property
    def openai_transcription_timeout(self) -> float:
        return float(os.getenv("OPENAI_TRANSCRIPTION_TIMEOUT", "3600.0"))

    @property
    def openai_embeddings_read_timeout(self) -> float:
        return float(os.getenv("OPENAI_EMBEDDINGS_READ_TIMEOUT", "30.0"))

    @property
    def anthropic_timeout(self) -> int:
        return int(os.getenv("ANTHROPIC_TIMEOUT", "600"))

    @property
    def ollama_connect_timeout(self) -> float:
        return float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "60.0"))

    def add_reload_callback(self, callback):
        self._on_reload_callbacks.append(callback)

    def reload_config(self):
        """Reload config from disk and invoke registered callbacks."""
        logger.info("Reloading configuration", extra={
            "config": {
                "operation": "reload_config",
                "config_dir": self.config_dir
            }
        })
        new_config = self._load_config(fail_on_error=False)
        if new_config.get('providers') and new_config.get('models') and new_config.get('user_keys'):
            self.config = new_config
            logger.info("Configuration reloaded", extra={
                "config": {
                    "operation": "reload_complete",
                    "providers_count": len(self.config.get('providers', {})),
                    "models_count": len(self.config.get('models', {})),
                    "user_keys_count": len(self.config.get('user_keys', {}))
                }
            })
            for cb in self._on_reload_callbacks:
                cb()
        else:
            logger.warning("Partial config reload rejected, keeping previous config")

    def _initialize_mtimes(self):
        config_files = [
            self.providers_path,
            self.models_path,
            self.user_keys_path,
        ]
        for fpath in config_files:
            try:
                self.last_mtimes[fpath] = os.path.getmtime(fpath)
            except FileNotFoundError:
                pass

    async def _reload_config_task(self):
        """Background task polling config files for mtime changes."""
        while True:
            try:
                changed = False
                config_files = [
                    self.providers_path,
                    self.models_path,
                    self.user_keys_path,
                ]
                for fpath in config_files:
                    try:
                        mtime = os.path.getmtime(fpath)
                        if fpath not in self.last_mtimes or self.last_mtimes[fpath] < mtime:
                            self.last_mtimes[fpath] = mtime
                            changed = True
                    except FileNotFoundError:
                        pass

                if changed:
                    logger.debug("Configuration files changed, triggering reload", extra={
                        "config": {
                            "operation": "auto_reload",
                            "changed_files": [fpath for fpath in config_files if fpath in self.last_mtimes]
                        }
                    })
                    self.reload_config()
            except asyncio.CancelledError:
                logger.info("Config reload task cancelled")
                return
            except Exception as e:
                logger.error(f"Config reload task error: {e}", exc_info=True)

            await asyncio.sleep(self.config_reload_interval)

    def start_reloader_task(self) -> asyncio.Task:
        return asyncio.create_task(self._reload_config_task())

# Example usage (for testing purposes)
if __name__ == "__main__":
    # Create dummy config files for testing
    os.makedirs("config", exist_ok=True)
    with open("config/providers.yaml", "w") as f:
        f.write("providers:\n  test_provider:\n    type: test\n")
    with open("config/models.yaml", "w") as f:
        f.write("models:\n  test_model:\n    provider: test_provider\n")
    with open("config/user_keys.yaml", "w") as f:
        f.write("user_keys:\n  test_key: {}\n")

    config_manager = ConfigManager()
    logger.info("Initial config loaded", extra={
        "config": {
            "operation": "test_initial_load",
            "config": config_manager.get_config()
        }
    })

    # Simulate a change and reload
    with open("config/providers.yaml", "w") as f:
        f.write("providers:\n  new_test_provider:\n    type: new_test\n")
    config_manager.reload_config()
    logger.info("Reloaded config for testing", extra={
        "config": {
            "operation": "test_reload",
            "config": config_manager.get_config()
        }
    })
