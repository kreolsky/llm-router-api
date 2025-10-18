import httpx
import asyncio
import os
import pytest
import logging

BASE_URL = "http://localhost:8777"

# API keys - use the dummy key that works with the running service
FULL_KEY = "dummy"
SHORT_KEY = "dummy"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_models_endpoint():
    logger.info("--- Testing /v1/models endpoint ---")

    # Test with 'full' user key
    logger.info(f"\nRequesting with 'full' user key: {FULL_KEY}")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {FULL_KEY}"})
        logger.info(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            models = response.json().get("data", [])
            logger.info(f"Number of models for 'full' user: {len(models)}")
        else:
            logger.error(f"Error: {response.json()}")

    # Test with 'short' user key
    logger.info(f"\nRequesting with 'short' user key: {SHORT_KEY}")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {SHORT_KEY}"})
        logger.info(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            models = response.json().get("data", [])
            logger.info(f"Number of models for 'short' user: {len(models)}")
            logger.info(f"Models: {[m['id'] for m in models]}")
        else:
            logger.error(f"Error: {response.json()}")

    # Test without API key
    logger.info("\nRequesting without API key (should be forbidden)")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models")
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Response: {response.json()}")

    # Test with non-existent API key
    non_existent_key = "nnp-v1-non-existent-key"
    logger.info(f"\nRequesting with non-existent API key: {non_existent_key} (should be forbidden)")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {non_existent_key}"})
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Response: {response.json()}")

@pytest.mark.asyncio
async def test_retrieve_model():
    logger.info("\n--- Testing /v1/models/{model_id} endpoint ---")

    # Test with 'full' user key
    model_id = "gemini/chat"
    logger.info(f"\nRequesting model '{model_id}' with 'full' user key")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models/{model_id}", headers={"Authorization": f"Bearer {FULL_KEY}"})
        logger.info(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            logger.info(f"Model details: {response.json()}")
        else:
            logger.error(f"Error: {response.json()}")

    # Test with 'short' user key
    logger.info(f"\nRequesting model '{model_id}' with 'short' user key")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models/{model_id}", headers={"Authorization": f"Bearer {SHORT_KEY}"})
        logger.info(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            logger.info(f"Model details: {response.json()}")
        else:
            logger.error(f"Error: {response.json()}")

    # Test with 'short' user key for a model not in their allowed list
    model_id = "mistral/mistral-small"  # Not in short user's allowed models
    logger.info(f"\nRequesting model '{model_id}' with 'short' user key (should be forbidden)")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models/{model_id}", headers={"Authorization": f"Bearer {SHORT_KEY}"})
        logger.info(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            logger.info(f"Model details: {response.json()}")
        else:
            logger.error(f"Error: {response.json()}")

@pytest.mark.asyncio
async def test_transcription():
    logger.info("\n--- Testing /v1/audio/transcriptions endpoint ---")

    # Test with 'full' user key
    logger.info("\nRequesting transcription with 'full' user key")
    async with httpx.AsyncClient(timeout=60.0) as client:
        with open("tests/transcription.ogg", "rb") as f:
            files = {"file": ("transcription.ogg", f, "audio/ogg")}
            data = {"model": "stt/dummy"}
            response = await client.post(
                f"{BASE_URL}/v1/audio/transcriptions",
                files=files,
                data=data,
                headers={"Authorization": f"Bearer {FULL_KEY}"}
            )
        logger.info(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            logger.info(f"Transcription result: {response.json()}")
        else:
            logger.error(f"Error: {response.json()}")

    # Test with 'short' user key
    logger.info("\nRequesting transcription with 'short' user key")
    async with httpx.AsyncClient(timeout=60.0) as client:
        with open("tests/transcription.ogg", "rb") as f:
            files = {"file": ("transcription.ogg", f, "audio/ogg")}
            data = {"model": "stt/dummy"}
            response = await client.post(
                f"{BASE_URL}/v1/audio/transcriptions",
                files=files,
                data=data,
                headers={"Authorization": f"Bearer {SHORT_KEY}"}
            )
        logger.info(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            logger.info(f"Transcription result: {response.json()}")
        else:
            logger.error(f"Error: {response.json()}")

if __name__ == "__main__":
    asyncio.run(test_models_endpoint())
    asyncio.run(test_retrieve_model())
    asyncio.run(test_transcription())