import secrets

def generate_key():
    # OpenRouter keys are typically sk-or-v1-<hex_string>
    # Generate a random 32-byte hex string for the unique part
    hex_string = secrets.token_hex(32)
    return f"nnp-v1-{hex_string}"
