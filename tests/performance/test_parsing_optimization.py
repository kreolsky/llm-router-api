import pytest
import time
from src.services.chat.smart_buffer_manager import SmartStreamBufferManager
import json
import tracemalloc

class TestParsingPerformance:
    def test_no_double_parsing_performance(self):
        """Тест что парсинг выполняется один раз"""
        manager = SmartStreamBufferManager()
        
        # 1000 SSE событий
        chunks = [
            b'data: {"choices":[{"delta":{"content":"X"}}]}\n\n' 
            for _ in range(1000)
        ]
        
        parse_count = 0
        original_json_loads = json.loads
        
        def counting_json_loads(*args, **kwargs):
            nonlocal parse_count
            parse_count += 1
            return original_json_loads(*args, **kwargs)
        
        # Monkey patch для подсчета
        json.loads = counting_json_loads
        
        start = time.time()
        for chunk in chunks:
            events = manager.process_chunk(chunk)
            for event in events:
                _ = event.content  # Используем кеш
        elapsed = time.time() - start
        
        # Восстанавливаем
        json.loads = original_json_loads
        
        # Должно быть 1000 парсингов (по одному на чанк)
        assert parse_count == 1000
        
        # Должно быть быстро (< 500ms)
        assert elapsed < 0.5
    
    def test_memory_efficiency(self):
        """Тест эффективности памяти"""
        tracemalloc.start()
        
        manager = SmartStreamBufferManager()
        chunks = [
            b'data: {"choices":[{"delta":{"content":"X"*100}}]}\n\n' 
            for _ in range(100)
        ]
        
        for chunk in chunks:
            events = manager.process_chunk(chunk)
            for event in events:
                _ = event.content
        
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        # Peak memory должна быть разумной (< 10MB)
        assert peak < 10 * 1024 * 1024