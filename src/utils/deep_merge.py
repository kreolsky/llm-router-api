"""Recursive dictionary merge utility."""

def deep_merge(dict1: dict, dict2: dict) -> dict:
    """Deep merges dict2 into dict1, returning a new dict without mutating inputs."""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value
        else:
            result[key] = value
    return result
