"""
Test for complete transparent proxying

This test verifies that all provider responses are returned as-is,
including reasoning content from models like deepseek-reasoner.
"""

import httpx
import json
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_complete_transparency():
    """Test that all provider responses are returned as-is"""
    
    # Test with reasoning model
    payload = {
        "model": "deepseek/reasoner",
        "messages": [{"role": "user", "content": "Solve step by step: 2+2*3"}],
        "stream": True
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy"
    }
    
    response_parts = []
    reasoning_parts = []
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", "http://localhost:8777/v1/chat/completions",
                                json=payload, headers=headers, timeout=30) as response:
            if response.status_code != 200:
                logger.error(f"Request failed with status {response.status_code}")
                logger.error(f"Response: {await response.aread()}")
                return False
                
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line.strip() != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        # Extract ALL content from delta, not just standard fields
                        if "choices" in chunk and chunk["choices"]:
                            delta = chunk["choices"][0].get("delta", {})
                            # Extract both content and reasoning_content
                            if delta.get("content"):
                                response_parts.append(delta["content"])
                            if delta.get("reasoning_content"):
                                reasoning_parts.append(delta["reasoning_content"])
                    except json.JSONDecodeError:
                        pass
    
    full_response = "".join(response_parts)
    full_reasoning = "".join(reasoning_parts)
    combined_response = full_reasoning + full_response
    
    print(f"Reasoning content: {full_reasoning}")
    print(f"Final answer: {full_response}")
    print(f"Combined response: {combined_response}")
    
    # Should contain reasoning steps, not just final answer
    has_reasoning = len(full_reasoning) > 10
    has_content = len(full_response) > 10
    
    success = has_reasoning and has_content
    if success:
        logger.info("✓ Test passed: Received complete response including reasoning")
    else:
        logger.error(f"✗ Test failed: reasoning={len(full_reasoning)}, content={len(full_response)}")
    
    # Additional checks for reasoning content
    reasoning_keywords = (
        "think" in full_reasoning.lower() or
        "reason" in full_reasoning.lower() or
        "step" in full_reasoning.lower() or
        "calculate" in full_reasoning.lower() or
        "multiply" in full_reasoning.lower() or
        "addition" in full_reasoning.lower()
    )
    
    if reasoning_keywords:
        logger.info("✓ Reasoning keywords detected in response")
    else:
        logger.warning("⚠ Could not detect reasoning keywords, but content may still be valid")
    
    return success

async def test_non_streaming_transparency():
    """Test that non-streaming responses are also transparent"""
    
    payload = {
        "model": "deepseek/reasoner",
        "messages": [{"role": "user", "content": "What is 2+2*3? Explain your reasoning."}],
        "stream": False
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer dummy"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post("http://localhost:8777/v1/chat/completions",
                                    json=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"Non-streaming request failed with status {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
        
        response_data = response.json()
        
        # Check that we have content
        if "choices" in response_data and response_data["choices"]:
            content = response_data["choices"][0].get("message", {}).get("content", "")
            print(f"Non-streaming response: {content}")
            
            success = len(content) > 50
            if success:
                logger.info("✓ Non-streaming test passed: Received complete response")
            else:
                logger.error("✗ Non-streaming test failed: Response too short")
            
            return success
        else:
            logger.error("✗ Non-streaming test failed: No choices in response")
            return False

async def main():
    """Run all transparency tests"""
    logger.info("Starting transparency tests...")
    
    streaming_success = await test_complete_transparency()
    non_streaming_success = await test_non_streaming_transparency()
    
    if streaming_success and non_streaming_success:
        logger.info("🎉 All transparency tests passed!")
        return True
    else:
        logger.error("❌ Some tests failed")
        return False

if __name__ == "__main__":
    asyncio.run(main())