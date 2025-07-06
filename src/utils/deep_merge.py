from typing import Dict, Any

def deep_merge(dict1: Dict, dict2: Dict) -> Dict:
    """Deep merges dict2 into dict1."""
    for key, value in dict2.items():
        if key in dict1 and isinstance(dict1[key], dict) and isinstance(value, dict):
            dict1[key] = deep_merge(dict1[key], value)
        else:
            dict1[key] = value
    return dict1
