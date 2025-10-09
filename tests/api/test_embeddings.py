"""
Embedding functionality tests for NNP LLM Router API.
"""

import pytest
import httpx
import numpy as np
import asyncio
from tests.test_utils import TestTimer, ResponseValidator


class TestEmbeddings:
    """Test embedding functionality."""
    
    @pytest.mark.asyncio
    async def test_create_embeddings(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        sample_texts_for_embedding: list,
        expected_embedding_response_structure: list,
        http_client: httpx.AsyncClient,
        performance_thresholds: dict
    ):
        """Test creating embeddings for sample texts."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": sample_texts_for_embedding,
            "encoding_format": "float"
        }
        
        with TestTimer() as timer:
            response = await http_client.post(
                f"{base_url}/v1/embeddings",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
        
        assert response.status_code == 200
        assert timer.elapsed < performance_thresholds["max_response_time"], \
            f"Response time {timer.elapsed:.3f}s exceeds threshold {performance_thresholds['max_response_time']}s"
        
        data = response.json()
        # Use the assertion function directly
        assert_valid_response_structure(data, expected_embedding_response_structure)
        
        # Verify response structure
        assert "data" in data
        assert "model" in data
        assert "usage" in data
        
        # Verify embeddings data
        embeddings = data["data"]
        assert len(embeddings) == len(sample_texts_for_embedding), "Should return one embedding per input text"
        
        # Verify each embedding structure
        for i, embedding in enumerate(embeddings):
            assert_valid_embedding_structure(embedding)
            assert embedding["index"] == i, f"Embedding index should match input order: {i}"
            
            # Verify embedding vector
            vector = embedding["embedding"]
            assert isinstance(vector, list), "Embedding should be a list"
            assert len(vector) > 0, "Embedding vector should not be empty"
            assert all(isinstance(x, (int, float)) for x in vector), "Embedding values should be numeric"
        
        # Verify model information
        assert isinstance(data["model"], str), "Model should be a string"
        assert len(data["model"]) > 0, "Model should not be empty"
        
        # Verify usage information
        usage = data["usage"]
        assert "prompt_tokens" in usage
        assert "total_tokens" in usage
        assert usage["total_tokens"] >= usage["prompt_tokens"]
    
    @pytest.mark.asyncio
    async def test_create_single_embedding(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embedding for a single text."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": "Hello, world!",
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "data" in data
        assert len(data["data"]) == 1, "Should return exactly one embedding"
        
        # Verify embedding structure
        embedding = data["data"][0]
        assert_valid_embedding_structure(embedding)
        assert embedding["index"] == 0, "Single embedding should have index 0"
        
        # Verify embedding vector
        vector = embedding["embedding"]
        assert isinstance(vector, list), "Embedding should be a list"
        assert len(vector) > 0, "Embedding vector should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_with_unicode(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with Unicode and emoji content."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        unicode_texts = [
            "Hello, world!",
            "Привет, мир!",
            "你好，世界！",
            "🌍🌎🌏 Earth emoji test"
        ]
        
        payload = {
            "model": model_id,
            "input": unicode_texts,
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        embeddings = data["data"]
        assert len(embeddings) == len(unicode_texts), "Should return one embedding per input text"
        
        # Verify each embedding has correct structure
        for i, embedding in enumerate(embeddings):
            assert_valid_embedding_structure(embedding)
            assert embedding["index"] == i, f"Embedding index should match input order: {i}"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_with_long_text(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with long text content."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        # Create a long text
        long_text = "This is a very long text. " * 100
        
        payload = {
            "model": model_id,
            "input": long_text,
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "data" in data
        assert len(data["data"]) == 1, "Should return exactly one embedding"
        
        # Verify usage information reflects long input
        usage = data["usage"]
        assert usage["prompt_tokens"] > 100, "Long text should use many tokens"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_with_multiple_inputs(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with multiple input texts."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        input_texts = [
            "First text",
            "Second text",
            "Third text",
            "Fourth text",
            "Fifth text"
        ]
        
        payload = {
            "model": model_id,
            "input": input_texts,
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        embeddings = data["data"]
        assert len(embeddings) == len(input_texts), "Should return one embedding per input text"
        
        # Verify each embedding has correct index
        for i, embedding in enumerate(embeddings):
            assert embedding["index"] == i, f"Embedding index should match input order: {i}"
        
        # Verify usage information
        usage = data["usage"]
        assert usage["prompt_tokens"] > len(input_texts), "Multiple texts should use multiple tokens"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_with_dimensions(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with specified dimensions."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": "Hello, world!",
            "encoding_format": "float",
            "dimensions": 128  # Request embeddings with 128 dimensions
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        # This might not be supported by all models, so we just check it doesn't error
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            data = response.json()
            embedding = data["data"][0]
            vector = embedding["embedding"]
            # If dimensions are supported, the vector should have the requested length
            # Otherwise, the vector might have the model's default dimensions
            assert len(vector) > 0, "Embedding vector should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_with_different_encoding_formats(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with different encoding formats."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        # Test with float encoding
        payload = {
            "model": model_id,
            "input": "Hello, world!",
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 200
        data = response.json()
        embedding = data["data"][0]
        vector = embedding["embedding"]
        
        # Float encoding should return a list of floats
        assert isinstance(vector, list), "Embedding should be a list"
        assert all(isinstance(x, (int, float)) for x in vector), "Embedding values should be numeric"
        
        # Test with base64 encoding (if supported)
        payload = {
            "model": model_id,
            "input": "Hello, world!",
            "encoding_format": "base64"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        # This might not be supported by all models
        assert response.status_code in [200, 400]
    
    @pytest.mark.asyncio
    async def test_create_embeddings_with_user_parameter(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with user parameter for monitoring."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": "Hello, world!",
            "encoding_format": "float",
            "user": "test-user-123"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        # This should be supported by most models
        assert response.status_code == 200
        data = response.json()
        
        # Verify response structure
        assert "data" in data
        assert len(data["data"]) == 1, "Should return exactly one embedding"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_invalid_model(
        self, 
        base_url: str, 
        api_keys: dict, 
        sample_texts_for_embedding: list,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with invalid model."""
        payload = {
            "model": "invalid/model/name",
            "input": sample_texts_for_embedding,
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code in [400, 404], "Should return error for invalid model"
        
        error_data = response.json()
        assert "error" in error_data or "detail" in error_data, "Should return error object"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_missing_required_fields(
        self, 
        base_url: str, 
        api_keys: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with missing required fields."""
        # Missing model field
        payload = {
            "input": ["Hello, world!"],
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 400, "Should return error for missing model"
        
        # Missing input field
        payload = {
            "model": "embeddings/dummy",
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 400, "Should return error for missing input"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_empty_input(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with empty input."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": [],
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 400, "Should return error for empty input"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_empty_string_input(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with empty string input."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": "",
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        # This might be handled differently by different models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            data = response.json()
            # If it succeeds, it should return a valid embedding
            assert "data" in data
            assert len(data["data"]) == 1, "Should return exactly one embedding"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_authentication(
        self, 
        base_url: str, 
        api_keys: dict, 
        sample_texts_for_embedding: list,
        http_client: httpx.AsyncClient
    ):
        """Test embedding creation authentication requirements."""
        payload = {
            "model": "embeddings/dummy",
            "input": sample_texts_for_embedding,
            "encoding_format": "float"
        }
        
        # Test without authentication
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 401, "Should require authentication"
        
        # Test with invalid authentication
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['invalid']}", "Content-Type": "application/json"},
            json=payload
        )
        
        assert response.status_code == 401, "Should reject invalid authentication"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_large_batch(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating embeddings with a large batch of inputs."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        # Create a large batch of inputs
        input_texts = [f"Text {i}" for i in range(100)]
        
        payload = {
            "model": model_id,
            "input": input_texts,
            "encoding_format": "float"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        # This might exceed limits for some models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            data = response.json()
            embeddings = data["data"]
            assert len(embeddings) == len(input_texts), "Should return one embedding per input text"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_concurrent_requests(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test concurrent embedding creation requests."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        async def make_request(request_id: int):
            payload = {
                "model": model_id,
                "input": f"Text for request {request_id}",
                "encoding_format": "float"
            }
            
            response = await http_client.post(
                f"{base_url}/v1/embeddings",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
            
            return response.status_code == 200
        
        # Make 5 concurrent requests
        tasks = [make_request(i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All requests should succeed
        successful_requests = sum(1 for result in results if result is True)
        assert successful_requests >= 4, f"At least 4 of 5 requests should succeed, got {successful_requests}"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_performance(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        performance_thresholds: dict,
        http_client: httpx.AsyncClient
    ):
        """Test embedding creation performance."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": ["Hello, world!", "This is a test."],
            "encoding_format": "float"
        }
        
        with TestTimer() as timer:
            response = await http_client.post(
                f"{base_url}/v1/embeddings",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
        
        assert response.status_code == 200
        assert timer.elapsed < performance_thresholds["max_response_time"], \
            f"Embedding creation took {timer.elapsed:.3f}s, threshold is {performance_thresholds['max_response_time']}s"
        
        # Check response size is reasonable
        response_size = len(response.content)
        assert response_size < 1024 * 1024, "Embedding response should be less than 1MB"
    
    @pytest.mark.asyncio
    async def test_create_embeddings_response_consistency(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test that embedding responses are consistent."""
        model_id = test_models["embeddings_dummy"]["id"]
        
        payload = {
            "model": model_id,
            "input": "Hello, world!",
            "encoding_format": "float"
        }
        
        # Make multiple requests with same parameters
        responses = []
        for _ in range(3):
            response = await http_client.post(
                f"{base_url}/v1/embeddings",
                headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
                json=payload
            )
            
            assert response.status_code == 200
            responses.append(response.json())
        
        # Extract embeddings from responses
        embeddings = [r["data"][0]["embedding"] for r in responses]
        
        # Embeddings should be very similar (might not be identical due to floating point precision)
        for i in range(1, len(embeddings)):
            # Calculate cosine similarity between embeddings
            embedding1 = np.array(embeddings[0])
            embedding2 = np.array(embeddings[i])
            
            # Normalize vectors
            embedding1_norm = embedding1 / np.linalg.norm(embedding1)
            embedding2_norm = embedding2 / np.linalg.norm(embedding2)
            
            # Calculate cosine similarity
            similarity = np.dot(embedding1_norm, embedding2_norm)
            
            # Cosine similarity should be very high (close to 1)
            assert similarity > 0.99, f"Embeddings should be very similar, similarity: {similarity}"


# Helper functions for response validation
def assert_valid_response_structure(response_data: dict, required_fields: list):
    """Assert that response contains all required fields."""
    for field in required_fields:
        assert field in response_data, f"Response missing required field: {field}"


def assert_valid_embedding_structure(embedding: dict):
    """Assert that embedding has valid structure."""
    required_fields = ["object", "embedding", "index"]
    for field in required_fields:
        assert field in embedding, f"Embedding missing required field: {field}"
    
    # Check embedding vector
    vector = embedding["embedding"]
    assert isinstance(vector, list), "Embedding should be a list"
    assert len(vector) > 0, "Embedding vector should not be empty"
    assert all(isinstance(x, (int, float)) for x in vector), "Embedding values should be numeric"