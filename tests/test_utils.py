"""
Test utilities and helper functions for NNP LLM Router test suite.
"""

import asyncio
import time
import json
import httpx
from typing import Dict, Any, List, Optional, AsyncGenerator
from pathlib import Path


class TestTimer:
    """Context manager for timing test operations."""
    
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.duration = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
    
    @property
    def elapsed(self) -> float:
        """Get elapsed time in seconds."""
        if self.duration is not None:
            return self.duration
        elif self.start_time is not None:
            return time.time() - self.start_time
        else:
            return 0.0


class StreamingResponseParser:
    """Parser for streaming API responses."""
    
    @staticmethod
    async def parse_sse_stream(response: httpx.Response) -> AsyncGenerator[Dict[str, Any], None]:
        """Parse Server-Sent Events (SSE) stream."""
        async for line in response.aiter_lines():
            if line.startswith('data: '):
                chunk_data = line[6:].strip()
                if chunk_data == '[DONE]':
                    break
                
                try:
                    data = json.loads(chunk_data)
                    yield data
                except json.JSONDecodeError:
                    continue
    
    @staticmethod
    async def parse_ndjson_stream(response: httpx.Response) -> AsyncGenerator[Dict[str, Any], None]:
        """Parse Newline Delimited JSON (NDJSON) stream."""
        async for line in response.aiter_lines():
            if line.strip():
                try:
                    data = json.loads(line)
                    yield data
                except json.JSONDecodeError:
                    continue
    
    @staticmethod
    async def collect_stream_content(
        response: httpx.Response, 
        stream_format: str = "sse"
    ) -> Dict[str, Any]:
        """Collect all content from a streaming response."""
        chunks = []
        full_content = ""
        first_chunk_time = None
        start_time = time.time()
        
        if stream_format == "sse":
            parser = StreamingResponseParser.parse_sse_stream
        else:
            parser = StreamingResponseParser.parse_ndjson_stream
        
        async for chunk in parser(response):
            if first_chunk_time is None:
                first_chunk_time = time.time()
            
            chunks.append(chunk)
            
            # Extract content if present
            if 'choices' in chunk and chunk['choices']:
                delta = chunk['choices'][0].get('delta', {})
                content = delta.get('content', '')
                full_content += content
        
        end_time = time.time()
        
        return {
            "chunks": chunks,
            "content": full_content,
            "chunk_count": len(chunks),
            "first_chunk_time": first_chunk_time,
            "ttft": first_chunk_time - start_time if first_chunk_time else None,
            "total_time": end_time - start_time,
            "chars_per_second": len(full_content) / (end_time - start_time) if end_time > start_time else 0
        }


class RetryHandler:
    """Handler for retrying failed requests."""
    
    @staticmethod
    async def retry_async(
        func,
        max_retries: int = 3,
        delay: float = 1.0,
        backoff_factor: float = 2.0,
        exceptions: tuple = (httpx.RequestError, httpx.TimeoutException)
    ) -> Any:
        """Retry an async function with exponential backoff."""
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                return await func()
            except exceptions as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = delay * (backoff_factor ** attempt)
                    await asyncio.sleep(wait_time)
                else:
                    raise last_exception


class ResponseValidator:
    """Validator for API responses."""
    
    @staticmethod
    def validate_chat_completion_response(response_data: Dict[str, Any]) -> bool:
        """Validate chat completion response structure."""
        required_fields = ["id", "object", "created", "model", "choices", "usage"]
        
        for field in required_fields:
            if field not in response_data:
                return False
        
        # Validate choices
        choices = response_data.get("choices", [])
        if not choices or not isinstance(choices, list):
            return False
        
        for choice in choices:
            if not isinstance(choice, dict):
                return False
            
            if "message" not in choice or "finish_reason" not in choice:
                return False
            
            message = choice["message"]
            if not isinstance(message, dict) or "role" not in message or "content" not in message:
                return False
        
        # Validate usage
        usage = response_data.get("usage", {})
        if not isinstance(usage, dict):
            return False
        
        return True
    
    @staticmethod
    def validate_embedding_response(response_data: Dict[str, Any]) -> bool:
        """Validate embedding response structure."""
        required_fields = ["data", "model", "usage"]
        
        for field in required_fields:
            if field not in response_data:
                return False
        
        # Validate data
        data = response_data.get("data", [])
        if not isinstance(data, list) or not data:
            return False
        
        for item in data:
            if not isinstance(item, dict):
                return False
            
            if "embedding" not in item or "index" not in item:
                return False
            
            embedding = item["embedding"]
            if not isinstance(embedding, list) or not embedding:
                return False
            
            if not all(isinstance(x, (int, float)) for x in embedding):
                return False
        
        return True
    
    @staticmethod
    def validate_model_list_response(response_data: Dict[str, Any]) -> bool:
        """Validate model list response structure."""
        required_fields = ["data", "object"]
        
        for field in required_fields:
            if field not in response_data:
                return False
        
        data = response_data.get("data", [])
        if not isinstance(data, list):
            return False
        
        for model in data:
            if not isinstance(model, dict):
                return False
            
            if "id" not in model:
                return False
        
        return True
    
    @staticmethod
    def validate_transcription_response(response_data: Dict[str, Any]) -> bool:
        """Validate transcription response structure."""
        if "text" not in response_data:
            return False
        
        text = response_data["text"]
        if not isinstance(text, str):
            return False
        
        return True


class TestDataGenerator:
    """Generator for test data."""
    
    @staticmethod
    def generate_chat_messages(
        count: int = 1,
        include_system: bool = False,
        include_unicode: bool = False
    ) -> List[Dict[str, str]]:
        """Generate chat messages for testing."""
        messages = []
        
        if include_system:
            messages.append({
                "role": "system",
                "content": "You are a helpful AI assistant."
            })
        
        base_messages = [
            "Hello! Tell me a short joke.",
            "What is the capital of France?",
            "Explain quantum computing in simple terms.",
            "Write a haiku about programming.",
            "What are the benefits of renewable energy?"
        ]
        
        unicode_messages = [
            "Respond in Russian: Привет! Как дела? 🤖",
            "Chinese test: 你好世界！🌏",
            "Emoji test: 🚀🎉🤖💻",
            "Mixed: Hello 世界 🌍 Bonjour le monde"
        ]
        
        message_pool = unicode_messages if include_unicode else base_messages
        
        for i in range(count):
            messages.append({
                "role": "user",
                "content": message_pool[i % len(message_pool)]
            })
        
        return messages
    
    @staticmethod
    def generate_embedding_texts(count: int = 3, include_unicode: bool = False) -> List[str]:
        """Generate texts for embedding testing."""
        base_texts = [
            "Hello, world!",
            "This is a test sentence.",
            "Embeddings are numerical representations of text.",
            "Machine learning models use embeddings for text processing.",
            "Natural language processing requires text vectorization."
        ]
        
        unicode_texts = [
            "Привет, мир!",
            "你好，世界！",
            "Bonjour le monde!",
            "Hola mundo! 🌍",
            "Test with emoji: 🤖🚀💻"
        ]
        
        text_pool = unicode_texts if include_unicode else base_texts
        
        return [text_pool[i % len(text_pool)] for i in range(count)]
    
    @staticmethod
    def generate_long_text(target_length: int = 1000) -> str:
        """Generate a long text for testing."""
        base_sentence = "This is a test sentence for generating long text content. "
        sentences_needed = max(1, target_length // len(base_sentence))
        
        long_text = (base_sentence * sentences_needed)[:target_length]
        return long_text


class PerformanceMonitor:
    """Monitor for performance metrics during tests."""
    
    def __init__(self):
        self.metrics = {}
    
    def start_timing(self, operation: str):
        """Start timing an operation."""
        self.metrics[operation] = {"start_time": time.time()}
    
    def end_timing(self, operation: str):
        """End timing an operation."""
        if operation in self.metrics:
            self.metrics[operation]["end_time"] = time.time()
            self.metrics[operation]["duration"] = (
                self.metrics[operation]["end_time"] - self.metrics[operation]["start_time"]
            )
    
    def get_duration(self, operation: str) -> Optional[float]:
        """Get duration of an operation."""
        return self.metrics.get(operation, {}).get("duration")
    
    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get all collected metrics."""
        return self.metrics.copy()


class FileHelper:
    """Helper for file operations in tests."""
    
    @staticmethod
    def ensure_test_audio_file(audio_path: Path) -> bool:
        """Ensure test audio file exists and is accessible."""
        if not audio_path.exists():
            return False
        
        if audio_path.stat().st_size == 0:
            return False
        
        return True
    
    @staticmethod
    def get_file_size(file_path: Path) -> int:
        """Get file size in bytes."""
        if file_path.exists():
            return file_path.stat().st_size
        return 0
    
    @staticmethod
    def create_temp_audio_file(temp_path: Path, duration_seconds: int = 5) -> bool:
        """Create a temporary audio file for testing (placeholder)."""
        # This is a placeholder - in real implementation, you might
        # generate or copy a test audio file
        return temp_path.exists()


# Utility functions for common test operations
async def make_authenticated_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    api_key: str,
    **kwargs
) -> httpx.Response:
    """Make an authenticated request to the API."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {api_key}"
    
    return await client.request(method, url, headers=headers, **kwargs)


async def check_service_health(base_url: str, timeout: float = 5.0) -> bool:
    """Check if the service is healthy."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{base_url}/health")
            return response.status_code == 200
    except:
        return False


def calculate_ttft_metrics(stream_data: Dict[str, Any]) -> Dict[str, float]:
    """Calculate Time to First Token metrics from stream data."""
    ttft = stream_data.get("ttft", 0)
    total_time = stream_data.get("total_time", 0)
    chunk_count = stream_data.get("chunk_count", 0)
    
    return {
        "ttft": ttft,
        "total_time": total_time,
        "chunks_per_second": chunk_count / total_time if total_time > 0 else 0,
        "ttft_ratio": ttft / total_time if total_time > 0 else 0
    }


def assert_performance_thresholds(
    metrics: Dict[str, float],
    thresholds: Dict[str, float]
) -> List[str]:
    """Assert that performance metrics meet thresholds."""
    violations = []
    
    for metric, value in metrics.items():
        if metric in thresholds:
            threshold = thresholds[metric]
            if value > threshold:
                violations.append(f"{metric}: {value:.3f} > {threshold:.3f}")
    
    return violations