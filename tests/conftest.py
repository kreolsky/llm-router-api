"""
Pytest configuration and fixtures for NNP LLM Router test suite.
"""

import os
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the API service."""
    return os.getenv("BASE_URL", "http://localhost:8777")


@pytest.fixture(scope="session")
def api_keys() -> dict[str, str]:
    """API keys for testing different access levels."""
    return {
        "full_access": "dummy",
        "limited": "limited",
        "transctiber": "transctiber",
        "invalid": "invalid-key-12345",
        "empty": ""
    }


@pytest.fixture(scope="session")
def test_models() -> dict[str, dict[str, Any]]:
    """Test models configuration."""
    return {
        "local_chat": {
            "id": "local/chat",
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
        "deepseek_flash": {
            "id": "deepseek/flash",
            "provider": "deepseek",
            "type": "chat",
            "streaming": True,
            "description": "DeepSeek V4 Flash model"
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
def sample_messages() -> list[dict[str, str]]:
    """Sample chat messages for testing."""
    return [
        {"role": "user", "content": "Hello! Tell me a short joke."}
    ]


@pytest.fixture
def unicode_messages() -> list[dict[str, str]]:
    """Unicode and emoji messages for testing."""
    return [
        {"role": "user", "content": "Respond in Russian with emojis: Что такое искусственный интеллект? 🤖🚀"}
    ]


@pytest.fixture
def long_message() -> dict[str, str]:
    """Long message for testing."""
    content = "This is a very long message. " * 100
    return {"role": "user", "content": content}


@pytest.fixture
def sample_texts_for_embedding() -> list[str]:
    """Sample texts for embedding tests."""
    return [
        "Hello, world!",
        "This is a test.",
        "Embeddings are useful."
    ]


@pytest.fixture
def expected_chat_response_structure() -> list[str]:
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
def expected_embedding_response_structure() -> list[str]:
    """Expected structure for embedding responses."""
    return [
        "data",
        "model",
        "usage"
    ]


@pytest.fixture
def expected_model_response_structure() -> list[str]:
    """Expected structure for model responses."""
    return [
        "data",
        "object"
    ]


@pytest.fixture
def performance_thresholds() -> dict[str, float]:
    """Performance thresholds for testing."""
    return {
        "max_response_time": 5.0,
        "max_ttft": 5.0,
        "min_throughput": 0.5,
        "max_memory_usage": 512.0
    }


@pytest.fixture
def streaming_test_config() -> dict[str, Any]:
    """Configuration for streaming tests."""
    return {
        "max_tokens": 50,
        "chunk_timeout": 10.0,
        "min_chunks": 1,
        "max_empty_chunks": 5
    }


# Custom assertions for test consistency
def assert_valid_response_structure(response_data: dict[str, Any], required_fields: list[str]):
    """Assert that response contains all required fields."""
    for field in required_fields:
        assert field in response_data, f"Response missing required field: {field}"


def assert_valid_choice_structure(choice: dict[str, Any]):
    """Assert that chat completion choice has valid structure."""
    required_fields = ["index", "message", "finish_reason"]
    for field in required_fields:
        assert field in choice, f"Choice missing required field: {field}"
    
    # Check message structure
    message = choice["message"]
    assert "role" in message, "Message missing role"
    assert "content" in message, "Message missing content"


def assert_valid_embedding_structure(embedding: dict[str, Any]):
    """Assert that embedding has valid structure."""
    required_fields = ["object", "embedding", "index"]
    for field in required_fields:
        assert field in embedding, f"Embedding missing required field: {field}"
    
    # Check embedding vector
    vector = embedding["embedding"]
    assert isinstance(vector, list), "Embedding should be a list"
    assert len(vector) > 0, "Embedding vector should not be empty"
    assert all(isinstance(x, (int, float)) for x in vector), "Embedding values should be numeric"

