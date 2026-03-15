from typing import Dict, Any

def deep_merge(dict1: Dict, dict2: Dict) -> Dict:
    """Deep merges dict2 into dict1, returning a new dict without mutating inputs."""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
