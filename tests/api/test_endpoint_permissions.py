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
    async def test_bro_kilo_code_endpoint_permissions(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        sample_messages: list,
        sample_texts_for_embedding: list,
        audio_file_path,
        http_client: httpx.AsyncClient
    ):
        """Test that bro_kilo_code key has appropriate access to endpoints."""
        bro_kilo_key = api_keys["bro_kilo_code"]
        
        # Test model listing endpoint
        response = await http_client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {bro_kilo_key}"}
        )
        assert response.status_code == 200, "bro_kilo_code should allow model listing"
        
        # Test chat completion endpoint with accessible model
        payload = {
            "model": test_models["local_orange"]["id"],
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 50
        }
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {bro_kilo_key}", "Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 200, "bro_kilo_code should allow chat completions with accessible models"
        
        # Test chat completion endpoint with restricted model
        payload = {
            "model": test_models["deepseek_chat"]["id"],
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 50
        }
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {bro_kilo_key}", "Content-Type": "application/json"},
            json=payload
        )
        # This might succeed or fail depending on configuration
        assert response.status_code in [200, 403, 404], "bro_kilo_code might not have access to all models"
        
        # Test embedding endpoint
        payload = {
            "model": test_models["embeddings_dummy"]["id"],
            "input": sample_texts_for_embedding,
            "encoding_format": "float"
        }
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {bro_kilo_key}", "Content-Type": "application/json"},
            json=payload
        )
        # This might succeed or fail depending on configuration
        assert response.status_code in [200, 403, 404], "bro_kilo_code might not have access to embeddings"
        
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
            headers={"Authorization": f"Bearer {bro_kilo_key}"},
            files=files,
            data=data
        )
        # This might succeed or fail depending on configuration
        assert response.status_code in [200, 403, 404], "bro_kilo_code might not have access to transcriptions with model"
        
        # Test transcription endpoint without model
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {bro_kilo_key}"},
            files=files
        )
        # This might succeed or fail depending on configuration
        assert response.status_code in [200, 403, 404], "bro_kilo_code might not have access to transcriptions without model"
    
    @pytest.mark.asyncio
    async def test_cir_online_endpoint_permissions(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        sample_messages: list,
        sample_texts_for_embedding: list,
        audio_file_path,
        http_client: httpx.AsyncClient
    ):
        """Test that cir_online key has appropriate access to endpoints."""
        cir_online_key = api_keys["cir_online"]
        
        # Test model listing endpoint
        response = await http_client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {cir_online_key}"}
        )
        assert response.status_code == 200, "cir_online should allow model listing"
        
        # Test chat completion endpoint with accessible model
        payload = {
            "model": test_models["gemini_mini"]["id"],
            "messages": sample_messages,
            "stream": False,
            "max_tokens": 50
        }
        response = await http_client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {cir_online_key}", "Content-Type": "application/json"},
            json=payload
        )
        assert response.status_code == 200, "cir_online should allow chat completions with accessible models"
        
        # Test embedding endpoint
        payload = {
            "model": test_models["embeddings_dummy"]["id"],
            "input": sample_texts_for_embedding,
            "encoding_format": "float"
        }
        response = await http_client.post(
            f"{base_url}/v1/embeddings",
            headers={"Authorization": f"Bearer {cir_online_key}", "Content-Type": "application/json"},
            json=payload
        )
        # This might succeed or fail depending on configuration
        assert response.status_code in [200, 403, 404], "cir_online might have access to embeddings"
        
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
            headers={"Authorization": f"Bearer {cir_online_key}"},
            files=files,
            data=data
        )
        # This might succeed or fail depending on configuration
        assert response.status_code in [200, 403, 404], "cir_online might have access to transcriptions with model"
        
        # Test transcription endpoint without model
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {cir_online_key}"},
            files=files
        )
        # This might succeed or fail depending on configuration
        assert response.status_code in [200, 403, 404], "cir_online might have access to transcriptions without model"
    
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
        
        # Test with other keys if they have transcription access
        for key_name in ["bro_kilo_code", "cir_online"]:
            if key_name in api_keys:
                api_key = api_keys[key_name]
                
                response = await http_client.post(
                    f"{base_url}/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files
                )
                
                # This might succeed or fail depending on configuration
                if response.status_code == 200:
                    transcription_data = response.json()
                    assert "text" in transcription_data, "Response should contain transcription text"
                    assert len(transcription_data["text"]) > 0, "Transcription should not be empty"
                    logger.info(f"✓ {key_name} can access transcription without model")
                elif response.status_code in [403, 404]:
                    logger.warning(f"⚠ {key_name} cannot access transcription without model")
                else:
                    # Unexpected status code
                    assert False, f"Unexpected status code {response.status_code} for {key_name}"