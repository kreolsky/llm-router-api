"""
Tools generate_key endpoint tests for NNP LLM Router API.
"""

import pytest
import httpx
import re
import asyncio
from tests.test_utils import TestTimer


class TestToolsGenerateKey:
    """Test tools generate_key endpoint functionality."""
    
    @pytest.mark.asyncio
    async def test_generate_key_endpoint(
        self, 
        base_url: str, 
        http_client: httpx.AsyncClient,
        performance_thresholds: dict
    ):
        """Test that the generate_key endpoint returns a valid key."""
        with TestTimer() as timer:
            response = await http_client.get(f"{base_url}/tools/generate_key")
        
        # Check response status and timing
        assert response.status_code == 200, "Should return 200 status code"
        assert timer.elapsed < performance_thresholds["max_response_time"], \
            f"Response time {timer.elapsed:.3f}s exceeds threshold {performance_thresholds['max_response_time']}s"
        
        # Check response structure
        data = response.json()
        assert "key" in data, "Response should contain a key field"
        
        # Check key format
        key = data["key"]
        assert isinstance(key, str), "Key should be a string"
        assert key.startswith("nnp-v1-"), "Key should start with 'nnp-v1-'"
        
        # Check that the hex part is valid (64 hex characters after the prefix)
        hex_part = key[7:]  # Remove "nnp-v1-" prefix
        assert len(hex_part) == 64, f"Key hex part should be 64 characters, got {len(hex_part)}"
        assert re.match(r'^[a-f0-9]+$', hex_part), "Key hex part should contain only lowercase hex characters"
    
    @pytest.mark.asyncio
    async def test_generate_key_no_auth_required(
        self, 
        base_url: str, 
        http_client: httpx.AsyncClient
    ):
        """Test that the generate_key endpoint works without authentication."""
        # Make request without Authorization header
        response = await http_client.get(f"{base_url}/tools/generate_key")
        
        assert response.status_code == 200, "Should succeed without authentication"
        
        data = response.json()
        assert "key" in data, "Response should contain a key field"
        assert data["key"].startswith("nnp-v1-"), "Key should have correct format"
    
    @pytest.mark.asyncio
    async def test_generate_key_with_invalid_auth(
        self, 
        base_url: str, 
        api_keys: dict, 
        http_client: httpx.AsyncClient
    ):
        """Test that the generate_key endpoint works even with invalid authentication."""
        # Make request with invalid Authorization header
        response = await http_client.get(
            f"{base_url}/tools/generate_key",
            headers={"Authorization": f"Bearer {api_keys['invalid']}"}
        )
        
        # Should still succeed since auth is not required
        assert response.status_code == 200, "Should succeed even with invalid auth"
        
        data = response.json()
        assert "key" in data, "Response should contain a key field"
        assert data["key"].startswith("nnp-v1-"), "Key should have correct format"
    
    @pytest.mark.asyncio
    async def test_generate_key_uniqueness(
        self, 
        base_url: str, 
        http_client: httpx.AsyncClient
    ):
        """Test that each request generates a unique key."""
        # Make multiple requests and collect keys
        keys = []
        for _ in range(5):
            response = await http_client.get(f"{base_url}/tools/generate_key")
            assert response.status_code == 200, "Each request should succeed"
            
            data = response.json()
            key = data["key"]
            keys.append(key)
        
        # Check that all keys are unique
        assert len(keys) == len(set(keys)), "All generated keys should be unique"
        
        # Check that all keys have valid format
        for key in keys:
            assert key.startswith("nnp-v1-"), "All keys should start with 'nnp-v1-'"
            hex_part = key[7:]  # Remove "nnp-v1-" prefix
            assert len(hex_part) == 64, "All keys should have 64-character hex part"
            assert re.match(r'^[a-f0-9]+$', hex_part), "All keys should have valid hex characters"
    
    @pytest.mark.asyncio
    async def test_generate_key_concurrent_requests(
        self, 
        base_url: str, 
        http_client: httpx.AsyncClient
    ):
        """Test that concurrent requests generate unique keys."""
        # Make concurrent requests
        async def make_request():
            response = await http_client.get(f"{base_url}/tools/generate_key")
            assert response.status_code == 200
            return response.json()["key"]
        
        # Create 10 concurrent requests
        tasks = [make_request() for _ in range(10)]
        keys = await asyncio.gather(*tasks)
        
        # Check that all keys are unique
        assert len(keys) == len(set(keys)), "Concurrent requests should generate unique keys"
        
        # Check that all keys have valid format
        for key in keys:
            assert key.startswith("nnp-v1-"), "All keys should start with 'nnp-v1-'"
            hex_part = key[7:]  # Remove "nnp-v1-" prefix
            assert len(hex_part) == 64, "All keys should have 64-character hex part"
            assert re.match(r'^[a-f0-9]+$', hex_part), "All keys should have valid hex characters"
    
    @pytest.mark.asyncio
    async def test_generate_key_response_headers(
        self, 
        base_url: str, 
        http_client: httpx.AsyncClient
    ):
        """Test that the generate_key endpoint returns appropriate headers."""
        response = await http_client.get(f"{base_url}/tools/generate_key")
        
        assert response.status_code == 200
        
        # Check for standard headers
        assert "content-type" in response.headers
        assert response.headers["content-type"] == "application/json"
        
        # Check that content length is reasonable
        content_length = int(response.headers["content-length"])
        assert content_length > 0, "Content length should be greater than 0"
        assert content_length < 1000, "Content length should be reasonable for a key response"
    
    @pytest.mark.asyncio
    async def test_generate_key_different_methods(
        self, 
        base_url: str, 
        http_client: httpx.AsyncClient
    ):
        """Test that only GET method is supported for the generate_key endpoint."""
        # Test POST method
        response = await http_client.post(f"{base_url}/tools/generate_key")
        # Should either succeed or return method not allowed
        assert response.status_code in [200, 405]
        
        # Test PUT method
        response = await http_client.put(f"{base_url}/tools/generate_key")
        # Should either succeed or return method not allowed
        assert response.status_code in [200, 405]
        
        # Test DELETE method
        response = await http_client.delete(f"{base_url}/tools/generate_key")
        # Should either succeed or return method not allowed
        assert response.status_code in [200, 405]
    
    @pytest.mark.asyncio
    async def test_generate_key_performance(
        self, 
        base_url: str, 
        http_client: httpx.AsyncClient,
        performance_thresholds: dict
    ):
        """Test generate_key endpoint performance."""
        # Make multiple requests and measure response times
        response_times = []
        for _ in range(10):
            with TestTimer() as timer:
                response = await http_client.get(f"{base_url}/tools/generate_key")
            
            assert response.status_code == 200
            response_times.append(timer.elapsed)
        
        # Calculate average response time
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)
        
        # Assert performance requirements
        assert avg_response_time < 1.0, f"Average response time {avg_response_time:.3f}s is too high"
        assert max_response_time < 2.0, f"Max response time {max_response_time:.3f}s is too high"
        assert max_response_time < performance_thresholds["max_response_time"], \
            f"Max response time {max_response_time:.3f}s exceeds threshold {performance_thresholds['max_response_time']}s"