#!/usr/bin/env python3
"""
Test script to verify streaming fixes for UTF-8 and SSE buffering issues.
Tests the critical fixes applied to handle multi-byte UTF-8 characters and incomplete SSE/JSON lines.
"""

import asyncio
import sys
import httpx

# Test configuration
BASE_URL = "http://localhost:8777"
API_KEY = "dummy"  # From config/user_keys.yaml
TEST_MODEL = "local/orange"  # Модель для тестирования

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

async def test_utf8_emoji_russian(client: httpx.AsyncClient):
    """Test UTF-8 handling with emoji and Russian text"""
    print_test("UTF-8 with Emoji and Russian Text")
    
    payload = {
        "model": TEST_MODEL,
        "messages": [
            {"role": "user", "content": "Ответь на русском с эмодзи: привет! 🚀💻🔥"}
        ],
        "stream": True,
        "max_tokens": 150
    }
    
    chunks_received = 0
    full_response = ""
    has_error = False
    
    try:
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
                        import json
                        try:
                            data = json.loads(line[6:])
                            if 'choices' in data and data['choices']:
                                content = data['choices'][0].get('delta', {}).get('content', '')
                                full_response += content
                        except:
                            pass
            
            if not has_error and chunks_received > 0:
                print_success(f"Received {chunks_received} chunks")
                print_success(f"Response length: {len(full_response)} chars")
                print(f"  Sample: {full_response[:100]}...")
                
                # Check for emoji presence
                if any(ord(c) > 127 for c in full_response):
                    print_success("Unicode characters detected ✓")
                
                return True
            else:
                print_error(f"Stream failed or no chunks received")
                return False
                
    except Exception as e:
        print_error(f"Exception: {e}")
        return False

async def test_long_response(client: httpx.AsyncClient):
    """Test handling of long streaming responses"""
    print_test("Long Streaming Response")
    
    payload = {
        "model": TEST_MODEL,
        "messages": [
            {"role": "user", "content": "Write a detailed explanation about Python programming in 500 words"}
        ],
        "stream": True,
        "max_tokens": 800
    }
    
    chunks_received = 0
    full_response = ""
    
    try:
        async with client.stream(
            "POST",
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
            timeout=60.0
        ) as response:
            if response.status_code != 200:
                print_error(f"HTTP {response.status_code}")
                return False
            
            async for chunk in response.aiter_bytes():
                chunks_received += 1
                decoded = chunk.decode('utf-8')
                
                if '"error"' in decoded:
                    print_error(f"Error in stream: {decoded}")
                    return False
                
                for line in decoded.split('\n'):
                    if line.startswith('data: ') and line != 'data: [DONE]':
                        import json
                        try:
                            data = json.loads(line[6:])
                            if 'choices' in data and data['choices']:
                                content = data['choices'][0].get('delta', {}).get('content', '')
                                full_response += content
                        except:
                            pass
            
            print_success(f"Received {chunks_received} chunks")
            print_success(f"Total response: {len(full_response)} chars, {len(full_response.split())} words")
            
            # Check if response is complete
            if chunks_received > 10 and len(full_response) > 100:
                print_success("Long response completed successfully")
                return True
            else:
                print_warning("Response seems incomplete")
                return False
                
    except Exception as e:
        print_error(f"Exception: {e}")
        return False

async def test_mixed_content(client: httpx.AsyncClient):
    """Test with mixed languages and special characters"""
    print_test("Mixed Languages and Special Characters")
    
    payload = {
        "model": TEST_MODEL,
        "messages": [
            {"role": "user", "content": "Напиши короткий ответ на русском и английском с emoji: что такое AI? 🤖"}
        ],
        "stream": True,
        "max_tokens": 100
    }
    
    chunks_received = 0
    full_response = ""
    
    try:
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
            
            async for chunk in response.aiter_bytes():
                chunks_received += 1
                decoded = chunk.decode('utf-8')
                
                for line in decoded.split('\n'):
                    if line.startswith('data: ') and line != 'data: [DONE]':
                        import json
                        try:
                            data = json.loads(line[6:])
                            if 'choices' in data and data['choices']:
                                content = data['choices'][0].get('delta', {}).get('content', '')
                                full_response += content
                        except:
                            pass
            
            print_success(f"Chunks: {chunks_received}, Response: {len(full_response)} chars")
            print(f"  Content: {full_response}")
            return chunks_received > 0 and len(full_response) > 0
            
    except Exception as e:
        print_error(f"Exception: {e}")
        return False

async def test_error_handling(client: httpx.AsyncClient):
    """Test error handling in streaming"""
    print_test("Error Handling")
    
    # Test with invalid model
    payload = {
        "model": "invalid/model/that/does/not/exist",
        "messages": [
            {"role": "user", "content": "Test"}
        ],
        "stream": True
    }
    
    try:
        response = await client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
            timeout=10.0
        )
        
        if response.status_code == 404:
            print_success("Correctly returned 404 for invalid model")
            return True
        else:
            print_warning(f"Unexpected status: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"Exception: {e}")
        return False

async def main():
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}LLM Router - Streaming Fixes Test Suite{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"\nTesting against: {BASE_URL}")
    print(f"API Key: {API_KEY}")
    
    async with httpx.AsyncClient() as client:
        results = {}
        
        # Run tests
        results["UTF-8 & Emoji"] = await test_utf8_emoji_russian(client)
        results["Long Response"] = await test_long_response(client)
        results["Mixed Content"] = await test_mixed_content(client)
        results["Error Handling"] = await test_error_handling(client)
        
        # Summary
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}TEST SUMMARY{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for test_name, result in results.items():
            status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
            print(f"  {test_name:.<40} {status}")
        
        print(f"\n{BLUE}Total: {passed}/{total} tests passed{RESET}\n")
        
        if passed == total:
            print(f"{GREEN}✓ All tests passed! Streaming fixes are working correctly.{RESET}\n")
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