import pytest
import httpx
import json
import time

# Assuming BASE_URL and API_KEY are defined elsewhere or mocked for E2E tests
# For a real E2E test, these would point to a running instance of the LLM Router
BASE_URL = "http://localhost:8777"
API_KEY = "dummy" # Replace with a valid API key for your setup

class TestRefactoredStreamingE2E:
    @pytest.mark.asyncio
    async def test_streaming_no_double_parsing_e2e(self):
        """
        Проверяем, что весь поток работает без двойного парсинга на E2E уровне.
        Это косвенная проверка, так как мы не можем напрямую отследить внутренний парсинг,
        но мы проверяем корректность и скорость ответа.
        """
        payload = {
            "model": "openai/gpt-4", # Use a model that supports streaming
            "messages": [{"role": "user", "content": "Tell me a short story about a brave knight."}],
            "stream": True,
            "max_tokens": 100
        }

        full_response_content = ""
        first_token_time = None
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}", "Accept": "text/event-stream"},
                    json=payload,
                    timeout=60.0
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith('data: '):
                            if first_token_time is None:
                                first_token_time = time.time()
                            
                            json_data = line[6:].strip()
                            if json_data == '[DONE]':
                                continue
                            
                            try:
                                data = json.loads(json_data)
                                # Assert that the structure is as expected for OpenAI-compatible SSE
                                assert 'choices' in data
                                assert len(data['choices']) > 0
                                delta = data['choices'][0].get('delta', {})
                                if 'content' in delta:
                                    full_response_content += delta['content']
                            except json.JSONDecodeError:
                                pytest.fail(f"Received invalid JSON in stream: {json_data}")
            
            end_time = time.time()
            total_latency = end_time - start_time
            ttft = first_token_time - start_time if first_token_time else float('inf')

            print(f"\nE2E Streaming Test Results:")
            print(f"  Total Latency: {total_latency:.2f}s")
            print(f"  Time To First Token (TTFT): {ttft:.2f}s")
            print(f"  Full Response Content Length: {len(full_response_content)}")
            
            assert len(full_response_content) > 0
            assert "knight" in full_response_content.lower() # Basic content check
            assert ttft < 10.0 # Expect TTFT to be reasonable
            assert total_latency < 30.0 # Expect total latency to be reasonable

        except httpx.HTTPStatusError as e:
            pytest.fail(f"HTTP error during E2E test: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            pytest.skip(f"E2E test skipped - server not running: {e}")
        except Exception as e:
            pytest.fail(f"An unexpected error occurred during E2E test: {e}")

    @pytest.mark.asyncio
    async def test_non_streaming_response_e2e(self):
        """
        Проверяем корректность не-стримингового ответа.
        """
        payload = {
            "model": "openai/gpt-4", # Use a model that supports non-streaming
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
            "max_tokens": 20
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                response_data = response.json()

                assert 'choices' in response_data
                assert len(response_data['choices']) > 0
                assert 'message' in response_data['choices'][0]
                assert 'content' in response_data['choices'][0]['message']
                assert "Paris" in response_data['choices'][0]['message']['content']

        except httpx.HTTPStatusError as e:
            pytest.fail(f"HTTP error during E2E non-streaming test: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            pytest.skip(f"E2E test skipped - server not running: {e}")
        except Exception as e:
            pytest.fail(f"An unexpected error occurred during E2E non-streaming test: {e}")