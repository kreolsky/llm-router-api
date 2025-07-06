import yaml
import os
import asyncio
import time
import logging # Import logging
from typing import Dict, Any

from ..logging.config import logger # Import logger from logging_config

class ConfigManager:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.providers_path = os.path.join(config_dir, "providers.yaml")
        self.models_path = os.path.join(config_dir, "models.yaml")
        self.user_keys_path = os.path.join(config_dir, "user_keys.yaml")
        self.config = self._load_config()
        self.last_mtimes = {} # Initialize last_mtimes as instance variable
        self._initialize_mtimes()

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
            # print(f"Configuration file not found: {e}") # Removed print for cleaner logs
            pass # Silently ignore missing files for now
        except yaml.YAMLError as e:
            print(f"Error parsing YAML file: {e}")
            # Handle YAML parsing errors
        return config

    def get_config(self) -> Dict[str, Any]:
        return self.config

    def reload_config(self):
        # print("Reloading configuration...") # Removed print for cleaner logs
        self.config = self._load_config()
        # print("Configuration reloaded.") # Removed print for cleaner logs

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
    print("Initial config:", config_manager.get_config())

    # Simulate a change and reload
    with open("config/providers.yaml", "w") as f:
        f.write("providers:\n  new_test_provider:\n    type: new_test\n")
    config_manager.reload_config()
    print("Reloaded config:", config_manager.get_config())
