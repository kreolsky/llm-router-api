"""
Pytest configuration and fixtures for NNP LLM Router test suite.
"""

import pytest
import pytest_asyncio
import httpx
import os
import asyncio
from typing import Dict, Any, List, Optional
from pathlib import Path


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the API service."""
    return os.getenv("BASE_URL", "http://localhost:8777")


@pytest.fixture(scope="session")
def api_keys() -> Dict[str, str]:
    """API keys for testing different access levels."""
    return {
        "full_access": "dummy",
        "limited_access": "nnp-v1-91afa1510b7e0c9d27b713ac0cc7a458775271f348d86c7ae823bf08f891e89a",
        "kilo_code": "nnp-v1-7572dd61f31870061fd4b9c809272a9070b36d7f6383171f71876e170ba2d07a",
        "dead_internet": "nnp-v1-16c34d52d13a9f02d9f417fa593bab5ba8d599ccb4a1023581a3c08ab383fa715",
        "bro_kilo_code": "nnp-v1-0897e56c94bc3fadec3c3e2a4378aa683919419d6127ced3b04a6785fbed7b57",
        "cir_online": "nnp-v1-6341ca3e67258db05c384d89c00eea3af998984cc8378ec45f606d4091cf827df",
        "invalid": "invalid-key-12345",
        "empty": ""
    }


@pytest.fixture(scope="session")
def test_models() -> Dict[str, Dict[str, Any]]:
    """Test models configuration."""
    return {
        "local_orange": {
            "id": "local/orange",
            "provider": "orange",
            "type": "chat",
            "streaming": True,
            "description": "Local model for testing"
        },
        "gemini_mini": {
            "id": "gemini/mini",
            "provider": "openrouter",
            "type": "chat",
            "streaming": True,
            "description": "OpenRouter Gemini Mini model"
        },
        "deepseek_chat": {
            "id": "deepseek/chat",
            "provider": "deepseek",
            "type": "chat",
            "streaming": True,
            "description": "Deepseek Chat model"
        },
        "embeddings_dummy": {
            "id": "embeddings/dummy",
            "provider": "embedding",
            "type": "embedding",
            "hidden": True,
            "description": "Hidden embedding model"
        },
        "stt_dummy": {
            "id": "stt/dummy",
            "provider": "transcriber",
            "type": "transcription",
            "hidden": True,
            "description": "Hidden transcription model"
        }
    }


@pytest.fixture(scope="session")
def timeout() -> float:
    """Request timeout in seconds."""
    return float(os.getenv("TIMEOUT", "30.0"))


@pytest.fixture(scope="session")
def retries() -> int:
    """Number of retry attempts for failed requests."""
    return int(os.getenv("RETRIES", "3"))


@pytest_asyncio.fixture
async def http_client(timeout: float) -> httpx.AsyncClient:
    """HTTP client for making requests."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        yield client


@pytest.fixture
def audio_file_path() -> Path:
    """Path to the test audio file."""
    return Path(__file__).parent / "transcription.ogg"


@pytest.fixture
def sample_messages() -> List[Dict[str, str]]:
    """Sample chat messages for testing."""
    return [
        {"role": "user", "content": "Hello! Tell me a short joke."}
    ]


@pytest.fixture
def unicode_messages() -> List[Dict[str, str]]:
    """Unicode and emoji messages for testing."""
    return [
        {"role": "user", "content": "Respond in Russian with emojis: Что такое искусственный интеллект? 🤖🚀"}
    ]


@pytest.fixture
def long_message() -> Dict[str, str]:
    """Long message for testing."""
    content = "This is a very long message. " * 100
    return {"role": "user", "content": content}


@pytest.fixture
def sample_texts_for_embedding() -> List[str]:
    """Sample texts for embedding tests."""
    return [
        "Hello, world!",
        "This is a test.",
        "Embeddings are useful."
    ]


@pytest.fixture(scope="session", autouse=True)
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def expected_chat_response_structure() -> List[str]:
    """Expected structure for chat completion responses."""
    return [
        "id",
        "object", 
        "created",
        "model",
        "choices",
        "usage"
    ]


@pytest.fixture
def expected_embedding_response_structure() -> List[str]:
    """Expected structure for embedding responses."""
    return [
        "data",
        "model",
        "usage"
    ]


@pytest.fixture
def expected_model_response_structure() -> List[str]:
    """Expected structure for model responses."""
    return [
        "data",
        "object"
    ]


@pytest.fixture
def performance_thresholds() -> Dict[str, float]:
    """Performance thresholds for testing."""
    return {
        "max_response_time": 5.0,
        "max_ttft": 2.0,
        "min_throughput": 0.5,
        "max_memory_usage": 512.0
    }


@pytest.fixture
def streaming_test_config() -> Dict[str, Any]:
    """Configuration for streaming tests."""
    return {
        "max_tokens": 50,
        "chunk_timeout": 10.0,
        "min_chunks": 1,
        "max_empty_chunks": 5
    }


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Setup test environment before each test."""
    # Set environment variables for testing
    os.environ["PYTHONPATH"] = str(Path(__file__).parent.parent)
    
    yield
    
    # Cleanup after test
    pass


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as performance test"
    )
    config.addinivalue_line(
        "markers", "streaming: mark test as streaming test"
    )
    config.addinivalue_line(
        "markers", "auth: mark test as authentication test"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test location."""
    for item in items:
        # Add slow marker for performance tests
        if "performance" in str(item.fspath):
            item.add_marker(pytest.mark.slow)
            item.add_marker(pytest.mark.performance)
        
        # Add integration marker for integration tests
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        
        # Add streaming marker for streaming tests
        if "streaming" in str(item.fspath):
            item.add_marker(pytest.mark.streaming)
        
        # Add auth marker for authentication tests
        if "auth" in str(item.fspath):
            item.add_marker(pytest.mark.auth)


@pytest.fixture
def skip_if_service_unavailable(base_url: str):
    """Skip test if service is not available."""
    async def check_service():
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{base_url}/health")
                return response.status_code == 200
        except:
            return False
    
    available = asyncio.run(check_service())
    if not available:
        pytest.skip("Service not available at {}".format(base_url))


# Custom assertions for test consistency
def assert_valid_response_structure(response_data: Dict[str, Any], required_fields: List[str]):
    """Assert that response contains all required fields."""
    for field in required_fields:
        assert field in response_data, f"Response missing required field: {field}"


def assert_valid_choice_structure(choice: Dict[str, Any]):
    """Assert that chat completion choice has valid structure."""
    required_fields = ["index", "message", "finish_reason"]
    for field in required_fields:
        assert field in choice, f"Choice missing required field: {field}"
    
    # Check message structure
    message = choice["message"]
    assert "role" in message, "Message missing role"
    assert "content" in message, "Message missing content"


def assert_valid_embedding_structure(embedding: Dict[str, Any]):
    """Assert that embedding has valid structure."""
    required_fields = ["object", "embedding", "index"]
    for field in required_fields:
        assert field in embedding, f"Embedding missing required field: {field}"
    
    # Check embedding vector
    vector = embedding["embedding"]
    assert isinstance(vector, list), "Embedding should be a list"
    assert len(vector) > 0, "Embedding vector should not be empty"
    assert all(isinstance(x, (int, float)) for x in vector), "Embedding values should be numeric"


# Make assertion functions available to tests
pytest.assert_valid_response_structure = assert_valid_response_structure
pytest.assert_valid_choice_structure = assert_valid_choice_structure
pytest.assert_valid_embedding_structure = assert_valid_embedding_structure