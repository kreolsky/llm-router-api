"""
Transcription functionality tests for NNP LLM Router API.
"""

import pytest
import httpx
import os
import base64
import asyncio
from pathlib import Path
from tests.test_utils import TestTimer, ResponseValidator


class TestTranscriptions:
    """Test transcription functionality."""
    
    @pytest.mark.asyncio
    async def test_create_transcription(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient,
        performance_thresholds: dict
    ):
        """Test creating transcription for audio file."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Create multipart form data
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": model_id
        }
        
        with TestTimer() as timer:
            response = await http_client.post(
                f"{base_url}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}"},
                files=files,
                data=data
            )
        
        assert response.status_code == 200
        assert timer.elapsed < performance_thresholds["max_response_time"], \
            f"Response time {timer.elapsed:.3f}s exceeds threshold {performance_thresholds['max_response_time']}s"
        
        # Verify response structure
        transcription_data = response.json()
        assert "text" in transcription_data, "Response should contain transcription text"
        assert len(transcription_data["text"]) > 0, "Transcription should not be empty"
        
        # Verify text content
        text = transcription_data["text"]
        assert isinstance(text, str), "Transcription should be a string"
    
    @pytest.mark.asyncio
    async def test_create_transcription_with_response_format(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with different response formats."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Test with JSON response format
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": model_id,
            "response_format": "json"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        assert response.status_code == 200
        transcription_data = response.json()
        assert "text" in transcription_data, "Response should contain transcription text"
        
        # Test with text response format
        data = {
            "model": model_id,
            "response_format": "text"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        # This might not be supported by all models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            # Should return plain text
            text = response.text
            assert len(text) > 0, "Transcription should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_transcription_with_language(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with specified language."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Test with English language
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": model_id,
            "language": "en"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        # This might not be supported by all models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            transcription_data = response.json()
            assert "text" in transcription_data, "Response should contain transcription text"
            assert len(transcription_data["text"]) > 0, "Transcription should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_transcription_with_temperature(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with temperature parameter."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Test with temperature
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": model_id,
            "temperature": 0.2
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        # This might not be supported by all models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            transcription_data = response.json()
            assert "text" in transcription_data, "Response should contain transcription text"
            assert len(transcription_data["text"]) > 0, "Transcription should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_transcription_with_timestamp_granularities(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with timestamp granularities."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Test with timestamp granularities
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": model_id,
            "timestamp_granularities": ["word", "segment"]
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        # This might not be supported by all models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            transcription_data = response.json()
            assert "text" in transcription_data, "Response should contain transcription text"
            assert len(transcription_data["text"]) > 0, "Transcription should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_transcription_with_prompt(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with prompt parameter."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Test with prompt
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": model_id,
            "prompt": "This is a test transcription."
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        # This might not be supported by all models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            transcription_data = response.json()
            assert "text" in transcription_data, "Response should contain transcription text"
            assert len(transcription_data["text"]) > 0, "Transcription should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_transcription_with_base64_audio(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with base64 encoded audio."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read and encode audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
            audio_base64 = base64.b64encode(audio_data).decode("utf-8")
        
        # Create JSON payload with base64 audio
        payload = {
            "model": model_id,
            "audio": audio_base64,
            "audio_format": "ogg"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}", "Content-Type": "application/json"},
            json=payload
        )
        
        # This might not be supported by all models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            transcription_data = response.json()
            assert "text" in transcription_data, "Response should contain transcription text"
            assert len(transcription_data["text"]) > 0, "Transcription should not be empty"
    
    @pytest.mark.asyncio
    async def test_create_transcription_invalid_model(
        self, 
        base_url: str, 
        api_keys: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with invalid model."""
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Create multipart form data
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": "invalid/model/name"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        assert response.status_code in [400, 404], "Should return error for invalid model"
        
        error_data = response.json()
        assert "error" in error_data or "detail" in error_data, "Should return error object"
    
    @pytest.mark.asyncio
    async def test_create_transcription_missing_required_fields(
        self, 
        base_url: str, 
        api_keys: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with missing required fields."""
        # Missing file field
        data = {
            "model": "stt/dummy"
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            data=data
        )
        
        assert response.status_code == 400, "Should return error for missing file"
        
        # Missing model field
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files={"file": ("test.ogg", b"fake audio data", "audio/ogg")}
        )
        
        assert response.status_code == 400, "Should return error for missing model"
    
    @pytest.mark.asyncio
    async def test_create_transcription_empty_file(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with empty file."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Create multipart form data with empty file
        files = {
            "file": ("empty.ogg", b"", "audio/ogg")
        }
        data = {
            "model": model_id
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        assert response.status_code == 400, "Should return error for empty file"
    
    @pytest.mark.asyncio
    async def test_create_transcription_authentication(
        self, 
        base_url: str, 
        api_keys: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test transcription creation authentication requirements."""
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Create multipart form data
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": "stt/dummy"
        }
        
        # Test without authentication
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            files=files,
            data=data
        )
        
        assert response.status_code == 401, "Should require authentication"
        
        # Test with invalid authentication
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['invalid']}"},
            files=files,
            data=data
        )
        
        assert response.status_code == 401, "Should reject invalid authentication"
    
    @pytest.mark.asyncio
    async def test_create_transcription_unsupported_format(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with unsupported audio format."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Create multipart form data with unsupported format
        files = {
            "file": ("test.xyz", b"fake audio data", "audio/xyz")
        }
        data = {
            "model": model_id
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        # This might be handled differently by different models
        assert response.status_code in [200, 400]
        
        if response.status_code == 200:
            transcription_data = response.json()
            assert "text" in transcription_data, "Response should contain transcription text"
    
    @pytest.mark.asyncio
    async def test_create_transcription_large_file(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict,
        http_client: httpx.AsyncClient
    ):
        """Test creating transcription with large file."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Create a large fake audio file
        large_audio_data = b"fake audio data" * 10000  # ~200KB
        
        # Create multipart form data
        files = {
            "file": ("large.ogg", large_audio_data, "audio/ogg")
        }
        data = {
            "model": model_id
        }
        
        response = await http_client.post(
            f"{base_url}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_keys['full_access']}"},
            files=files,
            data=data
        )
        
        # This might exceed limits for some models
        assert response.status_code in [200, 400, 413]
        
        if response.status_code == 200:
            transcription_data = response.json()
            assert "text" in transcription_data, "Response should contain transcription text"
    
    @pytest.mark.asyncio
    async def test_create_transcription_concurrent_requests(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test concurrent transcription creation requests."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        async def make_request(request_id: int):
            # Create multipart form data
            files = {
                "file": (f"test_{request_id}.ogg", audio_data, "audio/ogg")
            }
            data = {
                "model": model_id
            }
            
            response = await http_client.post(
                f"{base_url}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}"},
                files=files,
                data=data
            )
            
            return response.status_code == 200
        
        # Make 3 concurrent requests (limited due to file I/O)
        tasks = [make_request(i) for i in range(3)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All requests should succeed
        successful_requests = sum(1 for result in results if result is True)
        assert successful_requests >= 2, f"At least 2 of 3 requests should succeed, got {successful_requests}"
    
    @pytest.mark.asyncio
    async def test_create_transcription_performance(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        performance_thresholds: dict,
        http_client: httpx.AsyncClient
    ):
        """Test transcription creation performance."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Create multipart form data
        files = {
            "file": (audio_file_path.name, audio_data, "audio/ogg")
        }
        data = {
            "model": model_id
        }
        
        with TestTimer() as timer:
            response = await http_client.post(
                f"{base_url}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}"},
                files=files,
                data=data
            )
        
        assert response.status_code == 200
        assert timer.elapsed < performance_thresholds["max_response_time"], \
            f"Transcription creation took {timer.elapsed:.3f}s, threshold is {performance_thresholds['max_response_time']}s"
        
        # Check response size is reasonable
        response_size = len(response.content)
        assert response_size < 1024 * 1024, "Transcription response should be less than 1MB"
    
    @pytest.mark.asyncio
    async def test_create_transcription_response_consistency(
        self, 
        base_url: str, 
        api_keys: dict, 
        test_models: dict, 
        audio_file_path: Path,
        http_client: httpx.AsyncClient
    ):
        """Test that transcription responses are consistent."""
        model_id = test_models["stt_dummy"]["id"]
        
        # Check if audio file exists
        assert audio_file_path.exists(), f"Audio file not found at {audio_file_path}"
        
        # Read audio file
        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
        
        # Make multiple requests with same parameters
        responses = []
        for _ in range(3):
            # Create multipart form data
            files = {
                "file": (audio_file_path.name, audio_data, "audio/ogg")
            }
            data = {
                "model": model_id
            }
            
            response = await http_client.post(
                f"{base_url}/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_keys['full_access']}"},
                files=files,
                data=data
            )
            
            assert response.status_code == 200
            responses.append(response.json())
        
        # Extract transcriptions from responses
        transcriptions = [r["text"] for r in responses]
        
        # Transcriptions should be very similar (might not be identical due to randomness)
        # We just check that they're not empty and have reasonable length
        for transcription in transcriptions:
            assert len(transcription) > 0, "Transcription should not be empty"
            assert len(transcription) > 10, "Transcription should have reasonable length"