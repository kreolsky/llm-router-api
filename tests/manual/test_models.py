import httpx
import asyncio
import os
import pytest

BASE_URL = "http://localhost:8777"

# API keys - use the dummy key that works with the running service
FULL_KEY = "dummy"
SHORT_KEY = "dummy"

@pytest.mark.asyncio
async def test_models_endpoint():
    print("--- Testing /v1/models endpoint ---")

    # Test with 'full' user key
    print(f"\nRequesting with 'full' user key: {FULL_KEY}")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {FULL_KEY}"})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            models = response.json().get("data", [])
            print(f"Number of models for 'full' user: {len(models)}")
        else:
            print(f"Error: {response.json()}")

    # Test with 'short' user key
    print(f"\nRequesting with 'short' user key: {SHORT_KEY}")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {SHORT_KEY}"})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            models = response.json().get("data", [])
            print(f"Number of models for 'short' user: {len(models)}")
            print(f"Models: {[m['id'] for m in models]}")
        else:
            print(f"Error: {response.json()}")

    # Test without API key
    print("\nRequesting without API key (should be forbidden)")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")

    # Test with non-existent API key
    non_existent_key = "nnp-v1-non-existent-key"
    print(f"\nRequesting with non-existent API key: {non_existent_key} (should be forbidden)")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {non_existent_key}"})
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")

@pytest.mark.asyncio
async def test_retrieve_model():
    print("\n--- Testing /v1/models/{model_id} endpoint ---")

    # Test with 'full' user key
    model_id = "gemini/chat"
    print(f"\nRequesting model '{model_id}' with 'full' user key")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models/{model_id}", headers={"Authorization": f"Bearer {FULL_KEY}"})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print(f"Model details: {response.json()}")
        else:
            print(f"Error: {response.json()}")

    # Test with 'short' user key
    print(f"\nRequesting model '{model_id}' with 'short' user key")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models/{model_id}", headers={"Authorization": f"Bearer {SHORT_KEY}"})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print(f"Model details: {response.json()}")
        else:
            print(f"Error: {response.json()}")

    # Test with 'short' user key for a model not in their allowed list
    model_id = "mistral/mistral-small"  # Not in short user's allowed models
    print(f"\nRequesting model '{model_id}' with 'short' user key (should be forbidden)")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models/{model_id}", headers={"Authorization": f"Bearer {SHORT_KEY}"})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print(f"Model details: {response.json()}")
        else:
            print(f"Error: {response.json()}")

@pytest.mark.asyncio
async def test_transcription():
    print("\n--- Testing /v1/audio/transcriptions endpoint ---")

    # Test with 'full' user key
    print("\nRequesting transcription with 'full' user key")
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
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print(f"Transcription result: {response.json()}")
        else:
            print(f"Error: {response.json()}")

    # Test with 'short' user key
    print("\nRequesting transcription with 'short' user key")
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
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print(f"Transcription result: {response.json()}")
        else:
            print(f"Error: {response.json()}")

if __name__ == "__main__":
    asyncio.run(test_models_endpoint())
    asyncio.run(test_retrieve_model())
    asyncio.run(test_transcription())