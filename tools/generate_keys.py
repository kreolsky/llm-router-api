import os
import secrets

def generate_openrouter_key():
    # OpenRouter keys are typically sk-or-v1-<hex_string>
    # Generate a random 32-byte hex string for the unique part
    hex_string = secrets.token_hex(32)
    return f"nnp-v1-{hex_string}"

if __name__ == "__main__":
    num_keys = 2
    print(f"Generating {num_keys} OpenRouter-like keys:")
    for i in range(num_keys):
        key = generate_openrouter_key()
        print(f"Key {i+1}: {key}")
