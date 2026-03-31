"""API key generation utility."""
import secrets

def generate_key():
    """Generate an API key in nnp-v1-<64-hex-chars> format."""
    # OpenRouter keys are typically sk-or-v1-<hex_string>
    hex_string = secrets.token_hex(32)
    return f"nnp-v1-{hex_string}"
