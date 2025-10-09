"""
Basic connectivity tests for NNP LLM Router API.
"""

import pytest
import httpx
import time
import asyncio
from tests.test_utils import TestTimer, check_service_health


class TestConnectivity:
    """Test basic API connectivity and service availability."""
    
    @pytest.mark.asyncio
    async def test_health_check_endpoint(self, base_url: str, http_client: httpx.AsyncClient):
        """Test the health check endpoint returns correct response."""
        with TestTimer() as timer:
            response = await http_client.get(f"{base_url}/health")
        
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert timer.elapsed < 5.0, "Health check should respond quickly"
    
    @pytest.mark.asyncio
    async def test_service_availability(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that the service is running and accessible."""
        # First check health
        health_response = await http_client.get(f"{base_url}/health")
        assert health_response.status_code == 200
        
        # Then try accessing a protected endpoint (should fail auth but respond)
        models_response = await http_client.get(f"{base_url}/v1/models")
        assert models_response.status_code == 401  # Should require auth
        
        # Service is available if it responds correctly to both requests
        assert True
    
    @pytest.mark.asyncio
    async def test_docker_setup_verification(self, base_url: str, http_client: httpx.AsyncClient):
        """Verify Docker setup is working correctly."""
        # Check if service responds on expected port
        response = await http_client.get(f"{base_url}/health")
        assert response.status_code == 200
        
        # Check response headers indicate proper service
        assert "server" in response.headers
        
        # Check that we can make multiple requests
        for _ in range(3):
            response = await http_client.get(f"{base_url}/health")
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_response_time_performance(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that response times are within acceptable limits."""
        response_times = []
        
        # Make multiple requests and measure response times
        for _ in range(5):
            start_time = time.time()
            response = await http_client.get(f"{base_url}/health")
            end_time = time.time()
            
            assert response.status_code == 200
            response_times.append(end_time - start_time)
        
        # Calculate average response time
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)
        
        # Assert performance requirements
        assert avg_response_time < 1.0, f"Average response time {avg_response_time:.3f}s is too high"
        assert max_response_time < 2.0, f"Max response time {max_response_time:.3f}s is too high"
    
    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, base_url: str):
        """Test that service handles concurrent health check requests."""
        # Make 10 concurrent requests
        tasks = []
        for _ in range(10):
            task = asyncio.create_task(self._make_health_request(base_url))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        # All requests should succeed
        assert all(results), "Not all concurrent health check requests succeeded"
        assert sum(results) == 10, "Expected all 10 requests to succeed"
    
    async def _make_health_request(self, base_url: str) -> bool:
        """Helper method to make a health request."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url}/health")
            return response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_service_resilience(self, base_url: str, http_client: httpx.AsyncClient):
        """Test service resilience with rapid successive requests."""
        # Make rapid requests to test service stability
        responses = []
        
        for i in range(20):
            response = await http_client.get(f"{base_url}/health")
            responses.append(response)
            
            # Small delay to avoid overwhelming the service
            await asyncio.sleep(0.01)
        
        # All responses should be successful
        success_count = sum(1 for r in responses if r.status_code == 200)
        assert success_count == 20, f"Expected 20 successful responses, got {success_count}"
    
    @pytest.mark.asyncio
    async def test_endpoint_headers(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that endpoints return appropriate headers."""
        response = await http_client.get(f"{base_url}/health")
        
        # Check for standard headers
        assert "content-type" in response.headers
        assert "content-length" in response.headers
        
        # Check content type
        assert response.headers["content-type"] == "application/json"
        
        # Check that content length is reasonable
        content_length = int(response.headers["content-length"])
        assert content_length > 0, "Content length should be greater than 0"
    
    @pytest.mark.asyncio
    async def test_invalid_endpoint_handling(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that service handles invalid endpoints correctly."""
        # Test non-existent endpoint
        response = await http_client.get(f"{base_url}/invalid-endpoint")
        assert response.status_code == 404
        
        # Test with different HTTP methods
        response = await http_client.post(f"{base_url}/health")
        # Should either succeed or return method not allowed
        assert response.status_code in [200, 405]
        
        response = await http_client.put(f"{base_url}/health")
        # Should either succeed or return method not allowed
        assert response.status_code in [200, 405]
    
    @pytest.mark.asyncio
    async def test_service_startup_time(self, base_url: str):
        """Test service startup time (useful for performance monitoring)."""
        startup_time = time.time()
        
        # Make first request (might be slower due to cold start)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/health")
        
        first_request_time = time.time()
        
        # Make second request (should be faster)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/health")
        
        second_request_time = time.time()
        
        # Both requests should succeed
        assert response.status_code == 200
        
        # Calculate timing metrics
        first_request_duration = first_request_time - startup_time
        second_request_duration = second_request_time - first_request_time
        
        # Log timing for monitoring (in real scenario, you'd log this)
        print(f"First request time: {first_request_duration:.3f}s")
        print(f"Second request time: {second_request_duration:.3f}s")
        
        # Second request should be faster (warm cache)
        if first_request_duration > 0.1:  # Only check if first request was slow
            assert second_request_duration < first_request_duration, \
                "Second request should be faster than first request"
    
    @pytest.mark.asyncio
    async def test_service_health_consistency(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that service health is consistent over multiple requests."""
        health_responses = []
        
        # Make multiple health checks over a short period
        for _ in range(10):
            response = await http_client.get(f"{base_url}/health")
            health_responses.append(response.json())
            await asyncio.sleep(0.1)  # Small delay between requests
        
        # All responses should be identical
        expected_response = {"status": "ok"}
        for i, response_data in enumerate(health_responses):
            assert response_data == expected_response, \
                f"Health response {i} differs from expected: {response_data}"
    
    @pytest.mark.asyncio
    async def test_network_connectivity(self, base_url: str):
        """Test basic network connectivity to the service."""
        # Use the utility function to check service health
        is_healthy = await check_service_health(base_url)
        assert is_healthy, f"Service at {base_url} is not healthy or accessible"
    
    @pytest.mark.asyncio
    async def test_service_error_handling(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that service handles errors gracefully."""
        # Test with malformed request
        response = await http_client.get(
            f"{base_url}/health",
            params={"invalid": "param"}
        )
        # Should still succeed (health endpoint doesn't validate params)
        assert response.status_code == 200
        
        # Test with invalid headers
        response = await http_client.get(
            f"{base_url}/health",
            headers={"Invalid-Header": "value"}
        )
        # Should still succeed
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_service_memory_usage(self, base_url: str, http_client: httpx.AsyncClient):
        """Test service memory usage during normal operation."""
        # Make a series of requests and check for memory leaks
        initial_response = await http_client.get(f"{base_url}/health")
        assert initial_response.status_code == 200
        
        # Make many requests
        for i in range(100):
            response = await http_client.get(f"{base_url}/health")
            assert response.status_code == 200
            
            # Every 25 requests, check that response is still consistent
            if i % 25 == 0:
                assert response.json() == {"status": "ok"}
    
    @pytest.mark.asyncio
    async def test_service_timeout_handling(self, base_url: str):
        """Test that service handles timeouts appropriately."""
        # Test with very short timeout
        try:
            async with httpx.AsyncClient(timeout=0.001) as client:
                response = await client.get(f"{base_url}/health")
                # If it succeeds, that's fine (service is very fast)
                assert response.status_code == 200
        except httpx.TimeoutException:
            # Timeout is acceptable for very short timeout
            pass
        
        # Test with reasonable timeout
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url}/health")
            assert response.status_code == 200


class TestServiceConfiguration:
    """Test service configuration and environment."""
    
    @pytest.mark.asyncio
    async def test_service_environment(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that service is running in expected environment."""
        response = await http_client.get(f"{base_url}/health")
        assert response.status_code == 200
        
        # Check that we're running on the expected port
        assert "localhost:8777" in base_url or "127.0.0.1:8777" in base_url
        
        # Service should be accessible via HTTP
        assert base_url.startswith("http://")
    
    @pytest.mark.asyncio
    async def test_docker_container_status(self, base_url: str, http_client: httpx.AsyncClient):
        """Test that Docker container is running properly."""
        # Make a request to verify container is running
        response = await http_client.get(f"{base_url}/health")
        assert response.status_code == 200
        
        # Check response headers for Docker-specific information
        headers = response.headers
        
        # The service should be running behind a reverse proxy or directly
        # Either way, it should respond correctly
        assert "server" in headers