"""
Test utilities and helper functions for NNP LLM Router test suite.
"""

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx


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
    async def parse_sse_stream(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
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
    async def collect_stream_content(
        response: httpx.Response
    ) -> dict[str, Any]:
        """Collect all content from a streaming response."""
        chunks = []
        full_content = ""
        first_chunk_time = None
        start_time = time.time()

        async for chunk in StreamingResponseParser.parse_sse_stream(response):
            if first_chunk_time is None:
                first_chunk_time = time.time()

            chunks.append(chunk)

            # Extract content if present
            if 'choices' in chunk and chunk['choices']:
                delta = chunk['choices'][0].get('delta', {})
                content = delta.get('content') or ''
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


def calculate_ttft_metrics(stream_data: dict[str, Any]) -> dict[str, float]:
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
    metrics: dict[str, float],
    thresholds: dict[str, float]
) -> list[str]:
    """Assert that performance metrics meet thresholds."""
    violations = []
    
    for metric, value in metrics.items():
        if metric in thresholds:
            threshold = thresholds[metric]
            if value > threshold:
                violations.append(f"{metric}: {value:.3f} > {threshold:.3f}")
    
    return violations

def assistant_text(message: dict[str, Any]) -> str:
    """Visible text a model produced, wherever it landed.

    A reasoning model spends a small ``max_tokens`` budget on ``reasoning_content``
    and returns ``content`` empty or null, so an assertion over ``content`` alone
    measures the model's thinking budget rather than the router.
    """
    parts = (message.get("content"), message.get("reasoning_content"))
    return "".join(part for part in parts if isinstance(part, str))
