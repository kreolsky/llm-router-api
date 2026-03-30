"""
Endpoint permissions tests for NNP LLM Router API.
Tests that API keys have appropriate access to different endpoints.
"""

import pytest
import httpx
import logging
from tests.test_utils import TestTimer

logger = logging.getLogger(__name__)


class TestEndpointPermissions:
    """Test endpoint permissions for different API keys."""
    
    @pytest.mark.asyncio
    async def test_full_access_endpoint_permissions(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        sample_messages: list,
        sample_texts_for_embedding: list,
        audio_file_path,
        http_client: httpx.AsyncClient
    ):
        """Test that full access key has access to all endpoints."""
        full_access_key = api_keys["full_access"]
        
        # Test model listing endpoint
        response = await http_client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {full_access_key}"}
        )
        assert response.status_code == 200, "Full access should allow model listing"
        
        # Test chat completion endpoint
        payload = {
            "model": test_models["local_orange"]["id"],
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 50
        }
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {full_access_key}", "Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 200, "Full access should allow chat completions"
        
        # Test embedding endpoint
        payload = {
            "model": test_models["embeddings_dummy"]["id"],
            "input": sample_texts_for_embedding,
            "encoding_format": "float"
        }
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {full_access_key}", "Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 200, "Full access should allow embeddings"
        
        # Test transcription endpoint with model
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": test_models["stt_dummy"]["id"]
        }
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {full_access_key}"},
            files=files,
            data=data
        )
        assert response.status_code == 200, "Full access should allow transcriptions with model"
        
        # Test transcription endpoint without model
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {full_access_key}"},
            files=files
        )
        assert response.status_code == 200, "Full access should allow transcriptions without model"
    
    @pytest.mark.asyncio
    async def test_invalid_key_endpoint_permissions(
        self, 
        base_url: str, 
        api_keys: dict,
        http_client: httpx.AsyncClient
    ):
        """Test that invalid key is denied access to all endpoints."""
        invalid_key = api_keys["invalid"]
        
        # Test model listing endpoint
        response = await http_client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {invalid_key}"}
        )
        assert response.status_code == 401, "Invalid key should be denied access to model listing"
        
        # Test chat completion endpoint
        payload = {
            "model": "local/orange",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
            "max_tokens": 50
        }
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {invalid_key}", "Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 401, "Invalid key should be denied access to chat completions"
        
        # Test embedding endpoint
        payload = {
            "model": "embeddings/dummy",
            "input": ["Hello, world!"],
            "encoding_format": "float"
        }
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {invalid_key}", "Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 401, "Invalid key should be denied access to embeddings"
        
        # Test transcription endpoint
        files = {
            "file": ("test.ogg", b"fake audio data", "audio/ogg")
        }
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {invalid_key}"},
            files=files
        )
        assert response.status_code == 401, "Invalid key should be denied access to transcriptions"
    
    @pytest.mark.asyncio
    async def test_no_auth_endpoint_permissions(
        self, 
        base_url: str,
        http_client: httpx.AsyncClient
    ):
        """Test that requests without authentication are denied access to all endpoints."""
        # Test model listing endpoint
        response = await http_client.get(f"{base_url}/v1/models")
        assert response.status_code == 401, "No auth should be denied access to model listing"
        
        # Test chat completion endpoint
        payload = {
            "model": "local/orange",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
            "max_tokens": 50
        }
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 401, "No auth should be denied access to chat completions"
        
        # Test embedding endpoint
        payload = {
            "model": "embeddings/dummy",
            "input": ["Hello, world!"],
            "encoding_format": "float"
        }
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 401, "No auth should be denied access to embeddings"
        
        # Test transcription endpoint
        files = {
            "file": ("test.ogg", b"fake audio data", "audio/ogg")
        }
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            files=files
        )
        assert response.status_code == 401, "No auth should be denied access to transcriptions"
    
    @pytest.mark.asyncio
    async def test_transcription_without_model(
        self, 
        base_url: str, 
        api_keys: dict, 
        audio_file_path,
        http_client: httpx.AsyncClient
    ):
        """Test that transcription requests without model are processed correctly."""
        # Test with full access key
        full_access_key = api_keys["full_access"]
        
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {full_access_key}"},
            files=files
        )
        
        assert response.status_code == 200, "Transcription without model should succeed with full access"

        transcription_data = response.json()
        assert "text" in transcription_data, "Response should contain transcription text"
        assert len(transcription_data["text"]) > 0, "Transcription should not be empty"


class TestLimitedUserPermissions:
    """Test permissions for user with allowed_models: [local/orange] only."""

    @pytest.mark.asyncio
    async def test_limited_chat_allowed_model(
        self, base_url, api_keys, sample_messages, http_client
    ):
        """Chat completions with allowed model local/orange should succeed."""
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['limited']}", "Content-Type": "application/json"},
            json={"model": "local/orange", "messages": sample_messages, "stream": False, "max_tokens": 50}
        )
        assert response.status_code == 200, "limited user should access local/orange"

    @pytest.mark.asyncio
    async def test_limited_chat_denied_gemini(
        self, base_url, api_keys, sample_messages, http_client
    ):
        """Chat completions with gemini/mini should be denied (not in allowed_models)."""
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['limited']}", "Content-Type": "application/json"},
            json={"model": "gemini/mini", "messages": sample_messages, "stream": False, "max_tokens": 50}
        )
        assert response.status_code == 403, "limited user should be denied gemini/mini"

    @pytest.mark.asyncio
    async def test_limited_chat_denied_deepseek(
        self, base_url, api_keys, sample_messages, http_client
    ):
        """Chat completions with deepseek/chat should be denied (not in allowed_models)."""
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['limited']}", "Content-Type": "application/json"},
            json={"model": "deepseek/chat", "messages": sample_messages, "stream": False, "max_tokens": 50}
        )
        assert response.status_code == 403, "limited user should be denied deepseek/chat"

    @pytest.mark.asyncio
    async def test_limited_embeddings_denied(
        self, base_url, api_keys, sample_texts_for_embedding, http_client
    ):
        """Embeddings with embeddings/dummy should be denied (not in allowed_models)."""
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['limited']}", "Content-Type": "application/json"},
            json={"model": "embeddings/dummy", "input": sample_texts_for_embedding, "encoding_format": "float"}
        )
        assert response.status_code == 403, "limited user should be denied embeddings/dummy"

    @pytest.mark.asyncio
    async def test_limited_transcription_denied(
        self, base_url, api_keys, audio_file_path, http_client
    ):
        """Transcription should be denied — stt/dummy (default model) not in allowed_models."""
        with open(audio_file_path, "rb") as f:
            audio_data = f.read()

        # Without explicit model — defaults to stt/dummy, not in allowed_models
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['limited']}"},
            files={"file": (audio_file_path.name, audio_data, "audio/ogg")}
        )
        assert response.status_code == 403, "limited user should be denied transcription (default model not allowed)"

        # With explicit model — also not in allowed_models
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['limited']}"},
            files={"file": (audio_file_path.name, audio_data, "audio/ogg")},
            data={"model": "stt/dummy"}
        )
        assert response.status_code == 403, "limited user should be denied transcription (explicit stt/dummy)"

    @pytest.mark.asyncio
    async def test_limited_model_list_filtered(
        self, base_url, api_keys, http_client
    ):
        """Model listing should return only local/orange for limited user."""
        response = await http_client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {api_keys['limited']}"}
        )
        assert response.status_code == 200
        model_ids = [m["id"] for m in response.json()["data"]]
        assert model_ids == ["local/orange"], f"limited user should only see local/orange, got {model_ids}"

    @pytest.mark.asyncio
    async def test_limited_model_retrieve_allowed(
        self, base_url, api_keys, http_client
    ):
        """Retrieving local/orange should succeed for limited user."""
        response = await http_client.get(
            f"{base_url}/v1/models/local/orange",
            headers={"Authorization": f"Bearer {api_keys['limited']}"}
        )
        assert response.status_code == 200
        assert response.json()["id"] == "local/orange"

    @pytest.mark.asyncio
    async def test_limited_model_retrieve_denied(
        self, base_url, api_keys, http_client
    ):
        """Retrieving gemini/mini should return 403 for limited user."""
        response = await http_client.get(
            f"{base_url}/v1/models/gemini/mini",
            headers={"Authorization": f"Bearer {api_keys['limited']}"}
        )
        assert response.status_code == 403, "limited user should be denied retrieving gemini/mini"

    @pytest.mark.asyncio
    async def test_limited_generate_key(
        self, base_url, api_keys, http_client
    ):
        """Generate key should succeed — limited user has no endpoint restrictions."""
        response = await http_client.get(
            f"{base_url}/tools/generate_key",
            headers={"Authorization": f"Bearer {api_keys['limited']}"}
        )
        assert response.status_code == 200
        assert "key" in response.json()


class TestTransctiberUserPermissions:
    """Test permissions for user with allowed_endpoints: [/v1/audio/transcriptions, /v1/models]."""

    @pytest.mark.asyncio
    async def test_transctiber_transcription_allowed(
        self, base_url, api_keys, audio_file_path, http_client
    ):
        """Transcription should succeed — endpoint is allowed, no model restrictions."""
        with open(audio_file_path, "rb") as f:
            audio_data = f.read()

        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['transctiber']}"},
            files={"file": (audio_file_path.name, audio_data, "audio/ogg")},
            data={"model": "stt/dummy"}
        )
        assert response.status_code == 200
        assert "text" in response.json()

    @pytest.mark.asyncio
    async def test_transctiber_transcription_without_model(
        self, base_url, api_keys, audio_file_path, http_client
    ):
        """Transcription without explicit model should succeed (default model, no model restriction)."""
        with open(audio_file_path, "rb") as f:
            audio_data = f.read()

        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['transctiber']}"},
            files={"file": (audio_file_path.name, audio_data, "audio/ogg")}
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_transctiber_model_list_allowed(
        self, base_url, api_keys, http_client
    ):
        """Model listing should succeed and show all visible models (no model restriction)."""
        response = await http_client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {api_keys['transctiber']}"}
        )
        assert response.status_code == 200
        model_ids = [m["id"] for m in response.json()["data"]]
        for expected in ["local/orange", "gemini/mini", "deepseek/chat"]:
            assert expected in model_ids, f"transctiber should see {expected}"
        # Hidden models must not appear
        assert "embeddings/dummy" not in model_ids
        assert "stt/dummy" not in model_ids

    @pytest.mark.asyncio
    async def test_transctiber_model_retrieve_denied(
        self, base_url, api_keys, http_client
    ):
        """Retrieve individual model should return 403.

        By design: allowed_endpoints contains /v1/models but NOT /v1/models/{model_id:path}.
        Only the model list is needed for service compatibility.
        """
        response = await http_client.get(
            f"{base_url}/v1/models/local/orange",
            headers={"Authorization": f"Bearer {api_keys['transctiber']}"}
        )
        assert response.status_code == 403, "transctiber should be denied model retrieval (endpoint not in allowed_endpoints)"

    @pytest.mark.asyncio
    async def test_transctiber_chat_denied(
        self, base_url, api_keys, sample_messages, http_client
    ):
        """Chat completions should return 403 — endpoint not allowed."""
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_keys['transctiber']}", "Content-Type": "application/json"},
            json={"model": "local/orange", "messages": sample_messages, "stream": False, "max_tokens": 50}
        )
        assert response.status_code == 403, "transctiber should be denied chat completions"

    @pytest.mark.asyncio
    async def test_transctiber_embeddings_denied(
        self, base_url, api_keys, sample_texts_for_embedding, http_client
    ):
        """Embeddings should return 403 — endpoint not allowed."""
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {api_keys['transctiber']}", "Content-Type": "application/json"},
            json={"model": "embeddings/dummy", "input": sample_texts_for_embedding, "encoding_format": "float"}
        )
        assert response.status_code == 403, "transctiber should be denied embeddings"

    @pytest.mark.asyncio
    async def test_transctiber_generate_key_denied(
        self, base_url, api_keys, http_client
    ):
        """Generate key should return 403 — endpoint not allowed."""
        response = await http_client.get(
            f"{base_url}/tools/generate_key",
            headers={"Authorization": f"Bearer {api_keys['transctiber']}"}
        )
        assert response.status_code == 403, "transctiber should be denied generate_key"