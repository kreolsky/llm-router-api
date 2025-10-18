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
        self.config = self._load_config()
        self.last_mtimes = {} # Initialize last_mtimes as instance variable
        self._initialize_mtimes()
        
        # Загружаем переменные окружения
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

    def _load_config(self) -> Dict[str, Any]:
        config = {}
        try:
            with open(self.providers_path, 'r') as f:
                config['providers'] = yaml.safe_load(f).get('providers', {})
            with open(self.models_path, 'r') as f:
                config['models'] = yaml.safe_load(f).get('models', {})
            with open(self.user_keys_path, 'r') as f:
                config['user_keys'] = yaml.safe_load(f).get('user_keys', {})
        except FileNotFoundError as e:
            logger.warning(f"Configuration file not found: {e}", extra={
                "config": {
                    "error_type": "file_not_found",
                    "file_path": str(e.filename) if hasattr(e, 'filename') else 'unknown'
                }
            }, exc_info=True)
            pass # Silently ignore missing files for now
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML file: {e}", extra={
                "config": {
                    "error_type": "yaml_parse_error",
                    "error_message": str(e)
                }
            }, exc_info=True)
            # Handle YAML parsing errors
        return config

    def get_config(self) -> Dict[str, Any]:
        return self.config
    
    @property
    def is_debug_enabled(self) -> bool:
        """Возвращает True если включен режим отладки"""
        return self.debug
    
    @property
    def should_sanitize_messages(self) -> bool:
        """Возвращает True если нужно санитизировать сообщения"""
        return self.sanitize_messages

    def reload_config(self):
        logger.info("Reloading configuration", extra={
            "config": {
                "operation": "reload_config",
                "config_dir": self.config_dir
            }
        })
        self.config = self._load_config()
        logger.info("Configuration reloaded", extra={
            "config": {
                "operation": "reload_complete",
                "providers_count": len(self.config.get('providers', {})),
                "models_count": len(self.config.get('models', {})),
                "user_keys_count": len(self.config.get('user_keys', {}))
            }
        })

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
        while True:
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
            
            await asyncio.sleep(5) # Check every 5 seconds

    def start_reloader_task(self):
        asyncio.create_task(self._reload_config_task())

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
