import httpx
import asyncio
import os
import pytest
import logging

BASE_URL = "http://localhost:8777"

# API keys - use the dummy key that works with the running service
FULL_KEY = "dummy"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_hidden_models_visibility():
    logger.info("\n--- Testing /v1/models endpoint with hidden models ---")

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/v1/models", headers={"Authorization": f"Bearer {FULL_KEY}"})
        
        logger.info(f"Status Code: {response.status_code}")
        assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
        
        models_data = response.json().get("data", [])
        model_ids = [model["id"] for model in models_data]
        logger.info(f"Models returned: {model_ids}")

        # Assert that hidden models are NOT in the list
        assert "embeddings/dummy" not in model_ids, "Hidden model 'embeddings/dummy' should not be in the list"
        assert "stt/dummy" not in model_ids, "Hidden model 'stt/dummy' should not be in the list"
        
        # Assert that a visible model IS in the list (e.g., deepseek/chat)
        assert "deepseek/chat" in model_ids, "Visible model 'deepseek/chat' should be in the list"
        logger.info("Test for hidden models in /v1/models passed.")

@pytest.mark.asyncio
async def test_retrieve_hidden_model():
    logger.info("\n--- Testing /v1/models/{model_id} endpoint for hidden models ---")

    hidden_model_id_1 = "embeddings/dummy"
    hidden_model_id_2 = "stt/dummy"

    async with httpx.AsyncClient() as client:
        # Test retrieving the first hidden model
        response_1 = await client.get(f"{BASE_URL}/v1/models/{hidden_model_id_1}", headers={"Authorization": f"Bearer {FULL_KEY}"})
        logger.info(f"Status Code for {hidden_model_id_1}: {response_1.status_code}")
        assert response_1.status_code == 200, f"Expected status code 200 for {hidden_model_id_1}, got {response_1.status_code}"
        assert response_1.json().get("id") == hidden_model_id_1, f"Expected model ID {hidden_model_id_1}, got {response_1.json().get('id')}"
        logger.info(f"Successfully retrieved hidden model: {hidden_model_id_1}")

        # Test retrieving the second hidden model
        response_2 = await client.get(f"{BASE_URL}/v1/models/{hidden_model_id_2}", headers={"Authorization": f"Bearer {FULL_KEY}"})
        logger.info(f"Status Code for {hidden_model_id_2}: {response_2.status_code}")
        assert response_2.status_code == 200, f"Expected status code 200 for {hidden_model_id_2}, got {response_2.status_code}"
        assert response_2.json().get("id") == hidden_model_id_2, f"Expected model ID {hidden_model_id_2}, got {response_2.json().get('id')}"
        logger.info(f"Successfully retrieved hidden model: {hidden_model_id_2}")
        
        logger.info("Test for retrieving hidden models via /v1/models/{model_id} passed.")

@pytest.mark.asyncio
async def test_embedding_model_functionality():
    logger.info("\n--- Testing /v1/embeddings endpoint with hidden model ---")

    embedding_model_id = "embeddings/dummy"
    test_input = ["Hello, world!"]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/v1/embeddings",
            headers={
                "Authorization": f"Bearer {FULL_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": embedding_model_id,
                "input": test_input
            }
        )
        
        logger.info(f"Status Code for {embedding_model_id} embedding: {response.status_code}")
        assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
        
        response_json = response.json()
        assert "data" in response_json, "Response should contain 'data' field"
        assert isinstance(response_json["data"], list), "'data' field should be a list"
        assert len(response_json["data"]) == len(test_input), "Number of embeddings should match number of inputs"
        
        first_embedding_obj = response_json["data"][0]
        assert "embedding" in first_embedding_obj, "First item in 'data' should contain 'embedding'"
        assert isinstance(first_embedding_obj["embedding"], list), "Embedding should be a list"
        assert len(first_embedding_obj["embedding"]) > 0, "Embedding list should not be empty"
        
        logger.info(f"Successfully received embedding for hidden model: {embedding_model_id}")
        logger.info(f"Embedding result (first 5 values): {first_embedding_obj['embedding'][:5]}...")
        logger.info("Test for embedding model functionality passed.")

if __name__ == "__main__":
    asyncio.run(test_hidden_models_visibility())
    asyncio.run(test_retrieve_hidden_model())
    asyncio.run(test_embedding_model_functionality())