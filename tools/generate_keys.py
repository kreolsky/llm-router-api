import os
import secrets
import logging

# Set up basic logging for this utility script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def generate_openrouter_key():
    # OpenRouter keys are typically sk-or-v1-<hex_string>
    # Generate a random 32-byte hex string for the unique part
    hex_string = secrets.token_hex(32)
    return f"nnp-v1-{hex_string}"

if __name__ == "__main__":
    num_keys = 2
    logger.info(f"Generating {num_keys} NNP AI Router keys:")
    for i in range(num_keys):
        key = generate_openrouter_key()
        logger.info(f"Key {i+1}: {key}")
