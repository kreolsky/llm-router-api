#!/usr/bin/env python3
"""
Test script to verify streaming functionality with local/orange and deepseek/chat models
using dummy API key.
"""

import asyncio
import sys
import httpx
import json

# Test configuration
BASE_URL = "http://localhost:8777"
API_KEY = "dummy"  # From config/user_keys.yaml

# ANSI color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def print_test(name: str):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}TEST: {name}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")

def print_success(msg: str):
    print(f"{GREEN}✓ {msg}{RESET}")

def print_error(msg: str):
    print(f"{RED}✗ {msg}{RESET}")

def print_warning(msg: str):
    print(f"{YELLOW}⚠ {msg}{RESET}")

async def test_model_streaming(model_name: str, test_name: str):
    """Test streaming functionality for a specific model"""
    print_test(f"Streaming Test: {test_name}")
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": "Привет! Расскажи о себе в нескольких словах."}
        ],
        "stream": True,
        "max_tokens": 100
    }
    
    chunks_received = 0
    full_response = ""
    has_error = False
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=30.0
            ) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    print(f"Response: {response.text}")
                    return False
                
                print_success(f"HTTP {response.status_code} - Connection established")
                
                async for chunk in response.aiter_bytes():
                    chunks_received += 1
                    decoded = chunk.decode('utf-8')
                    
                    # Check for errors in stream
                    if '"error"' in decoded:
                        print_error(f"Error in stream: {decoded}")
                        has_error = True
                        break
                    
                    # Extract content from SSE
                    for line in decoded.split('\n'):
                        if line.startswith('data: ') and line != 'data: [DONE]':
                            try:
                                data = json.loads(line[6:])
                                if 'choices' in data and data['choices']:
                                    content = data['choices'][0].get('delta', {}).get('content', '')
                                    full_response += content
                            except json.JSONDecodeError:
                                print_warning(f"Failed to parse JSON: {line}")
                            except Exception as e:
                                print_warning(f"Error processing chunk: {e}")
                
                if not has_error and chunks_received > 0:
                    print_success(f"Received {chunks_received} chunks")
                    print_success(f"Response length: {len(full_response)} chars")
                    print(f"  Content: {full_response}")
                    
                    # Check for content
                    if len(full_response) > 0:
                        print_success("Content received successfully ✓")
                        print(f"  Average chunk size: {len(full_response) / chunks_received:.1f} chars per chunk")
                        return True
                    else:
                        print_error("No content received")
                        return False
                else:
                    print_error(f"Stream failed or no chunks received")
                    return False
                    
    except Exception as e:
        print_error(f"Exception: {e}")
        return False

async def test_model_with_emoji(model_name: str, test_name: str):
    """Test streaming with emoji and special characters"""
    print_test(f"Emoji Test: {test_name}")
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": "Ответь на русском с эмодзи: что такое искусственный интеллект? 🤖🚀"}
        ],
        "stream": True,
        "max_tokens": 150
    }
    
    chunks_received = 0
    full_response = ""
    has_error = False
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=30.0
            ) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    return False
                
                print_success(f"HTTP {response.status_code} - Connection established")
                
                async for chunk in response.aiter_bytes():
                    chunks_received += 1
                    decoded = chunk.decode('utf-8')
                    
                    # Check for errors in stream
                    if '"error"' in decoded:
                        print_error(f"Error in stream: {decoded}")
                        has_error = True
                        break
                    
                    # Extract content from SSE
                    for line in decoded.split('\n'):
                        if line.startswith('data: ') and line != 'data: [DONE]':
                            try:
                                data = json.loads(line[6:])
                                if 'choices' in data and data['choices']:
                                    content = data['choices'][0].get('delta', {}).get('content', '')
                                    full_response += content
                            except json.JSONDecodeError:
                                print_warning(f"Failed to parse JSON: {line}")
                
                if not has_error and chunks_received > 0:
                    print_success(f"Received {chunks_received} chunks")
                    print_success(f"Response length: {len(full_response)} chars")
                    print(f"  Content: {full_response}")
                    
                    # Check for emoji presence
                    if any(ord(c) > 127 for c in full_response):
                        print_success("Unicode characters detected ✓")
                    else:
                        print_warning("No Unicode characters detected")
                    
                    print(f"  Average chunk size: {len(full_response) / chunks_received:.1f} chars per chunk")
                    return len(full_response) > 0
                else:
                    print_error(f"Stream failed or no chunks received")
                    return False
                    
    except Exception as e:
        print_error(f"Exception: {e}")
        return False

async def test_available_models():
    """Test if models are available with dummy key"""
    print_test("Available Models Check")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/v1/models",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                models = [model['id'] for model in data.get('data', [])]
                
                print_success(f"Available models: {len(models)}")
                
                # Check if our test models are available
                if 'local/orange' in models:
                    print_success("✓ local/orange is available")
                else:
                    print_error("✗ local/orange is not available")
                
                if 'deepseek/chat' in models:
                    print_success("✓ deepseek/chat is available")
                else:
                    print_error("✗ deepseek/chat is not available")
                
                return True
            else:
                print_error(f"HTTP {response.status_code}: {response.text}")
                return False
                
    except Exception as e:
        print_error(f"Exception: {e}")
        return False

async def main():
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}LLM Router - Streaming Test Suite{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"\nTesting against: {BASE_URL}")
    print(f"API Key: {API_KEY}")
    
    async with httpx.AsyncClient() as client:
        results = {}
        
        # First check available models
        results["Available Models"] = await test_available_models()
        
        # Test local/orange model
        results["local/orange - Basic Streaming"] = await test_model_streaming("local/orange", "Local Orange Basic")
        results["local/orange - Emoji Test"] = await test_model_with_emoji("local/orange", "Local Orange Emoji")
        
        # Test deepseek/chat model
        results["deepseek/chat - Basic Streaming"] = await test_model_streaming("deepseek/chat", "Deepseek Chat Basic")
        results["deepseek/chat - Emoji Test"] = await test_model_with_emoji("deepseek/chat", "Deepseek Chat Emoji")
        
        # Summary
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}TEST SUMMARY{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for test_name, result in results.items():
            status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
            print(f"  {test_name:.<50} {status}")
        
        print(f"\n{BLUE}Total: {passed}/{total} tests passed{RESET}\n")
        
        if passed == total:
            print(f"{GREEN}✓ All tests passed! Streaming is working correctly.{RESET}\n")
            return 0
        else:
            print(f"{RED}✗ Some tests failed. Please check the output above.{RESET}\n")
            return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Tests interrupted by user{RESET}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Fatal error: {e}{RESET}\n")
        sys.exit(1)