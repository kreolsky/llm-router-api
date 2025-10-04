#!/usr/bin/env python3
"""
Test script to verify statistics functionality
"""
import asyncio
import json
import time
from src.services.chat_service.statistics_collector import StatisticsCollector
from src.services.chat_service.stream_processor import StreamProcessor


async def test_statistics_collector():
    """Test StatisticsCollector functionality"""
    print("🧪 Testing StatisticsCollector...")
    
    collector = StatisticsCollector()
    
    # Test timing
    collector.start_timing()
    time.sleep(0.1)  # Simulate prompt processing
    collector.mark_prompt_complete(100)  # 100 prompt tokens
    time.sleep(0.2)  # Simulate completion generation
    collector.mark_completion_complete(50)  # 50 completion tokens
    
    stats = collector.get_statistics()
    
    print("📊 Statistics collected:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Verify expected fields
    expected_fields = [
        "prompt_tokens", "prompt_time", "prompt_tokens_per_sec",
        "completion_tokens", "completion_time", "completion_tokens_per_sec",
        "total_tokens", "total_time"
    ]
    
    for field in expected_fields:
        assert field in stats, f"Missing field: {field}"
        print(f"  ✅ {field}: {stats[field]}")
    
    # Verify calculations
    assert stats["prompt_tokens"] == 100
    assert stats["completion_tokens"] == 50
    assert stats["total_tokens"] == 150
    assert stats["prompt_time"] > 0
    assert stats["completion_time"] > 0
    assert stats["total_time"] > 0
    
    print("✅ StatisticsCollector test passed!")


async def test_stream_processor_statistics():
    """Test StreamProcessor statistics functionality"""
    print("\n🧪 Testing StreamProcessor statistics...")
    
    processor = StreamProcessor()
    
    # Test token estimation
    test_text = "Hello world, this is a test message with multiple words."
    estimated_tokens = processor._estimate_tokens(test_text)
    print(f"  Estimated tokens for '{test_text}': {estimated_tokens}")
    
    # Test statistics event formatting
    test_stats = {
        "prompt_tokens": 100,
        "prompt_time": 0.15,
        "prompt_tokens_per_sec": 666.67,
        "completion_tokens": 50,
        "completion_time": 0.25,
        "completion_tokens_per_sec": 200.0,
        "total_tokens": 150,
        "total_time": 0.4
    }
    
    stats_event = processor._format_statistics_event(test_stats, "test-123", "test-model")
    stats_event_str = stats_event.decode('utf-8')
    print(f"  Statistics event format: {stats_event_str.strip()}")
    
    # Verify event format
    assert stats_event_str.startswith("data: ")
    assert "[DONE]" not in stats_event_str  # Should not be the DONE event
    
    # Parse and verify content
    event_data = json.loads(stats_event_str[6:].strip())  # Remove "data: " prefix
    # Verify all statistics fields are present
    for key, value in test_stats.items():
        assert event_data[key] == value, f"Field {key} mismatch: {event_data[key]} != {value}"
    
    print("✅ StreamProcessor statistics test passed!")


async def main():
    """Run all tests"""
    print("🚀 Starting statistics functionality tests...\n")
    
    await test_statistics_collector()
    await test_stream_processor_statistics()
    
    print("\n🎉 All statistics tests completed successfully!")
    print("\n📋 Summary of implemented features:")
    print("  ✅ StatisticsCollector class for timing and token tracking")
    print("  ✅ StreamProcessor with statistics collection")
    print("  ✅ Final statistics event for streaming responses")
    print("  ✅ Enhanced usage field for non-streaming responses")
    print("  ✅ Token estimation for streaming responses")
    print("  ✅ Performance metrics (tokens per second)")
    print("  ✅ Timing metrics (prompt_time, completion_time, total_time)")


if __name__ == "__main__":
    asyncio.run(main())