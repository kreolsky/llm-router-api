"""
Тест упрощенного StreamProcessor
"""
import pytest
import json
from src.services.chat_service.stream_processor import StreamProcessor


class TestStreamProcessorSimplified:
    """Тесты упрощенного StreamProcessor"""
    
    def setup_method(self):
        self.processor = StreamProcessor()
    
    def test_detect_sse_format(self):
        """Тест определения SSE формата"""
        sse_event = "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}"
        assert self.processor._detect_format(sse_event) == 'sse'
    
    def test_detect_ndjson_format(self):
        """Тест определения NDJSON формата"""
        ndjson_event = "{\"message\": {\"content\": \"Hello\"}}"
        assert self.processor._detect_format(ndjson_event) == 'ndjson'
    
    def test_parse_sse_event(self):
        """Тест парсинга SSE события"""
        sse_event = "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}"
        result = self.processor._parse_sse_event(sse_event)
        assert result is not None
        assert 'choices' in result
        assert result['choices'][0]['delta']['content'] == 'Hello'
    
    def test_parse_sse_done_event(self):
        """Тест парсинга SSE [DONE] события"""
        sse_done = "data: [DONE]"
        result = self.processor._parse_sse_event(sse_done)
        assert result == {'done': True}
    
    def test_extract_content_from_sse(self):
        """Тест извлечения контента из SSE"""
        event_data = {
            'choices': [{
                'delta': {'content': 'Hello'}
            }]
        }
        content = self.processor._extract_content_from_data(event_data)
        assert content == 'Hello'
    
    def test_extract_content_from_ndjson(self):
        """Тест извлечения контента из NDJSON"""
        event_data = {
            'message': {'content': 'Hello'}
        }
        content = self.processor._extract_content_from_data(event_data)
        assert content == 'Hello'
    
    def test_format_sse_chunk(self):
        """Тест форматирования SSE чанка"""
        content = "Hello"
        model_id = "test-model"
        request_id = "test-request"
        
        chunk = self.processor._format_sse_chunk(content, model_id, request_id)
        assert chunk is not None
        assert b'data: ' in chunk
        assert b'Hello' in chunk
        assert b'test-model' in chunk
    
    def test_format_error(self):
        """Тест форматирования ошибки"""
        error = Exception("Test error")
        error_chunk = self.processor._format_error(error)
        assert error_chunk is not None
        assert b'data: ' in error_chunk
        assert b'Test error' in error_chunk
    
    def test_extract_sse_events(self):
        """Тест извлечения SSE событий из буфера"""
        self.processor.buffer = "data: {\"content\": \"Hello\"}\n\ndata: {\"content\": \"World\"}\n\n"
        events = self.processor._extract_sse_events(final=False)
        assert len(events) == 2
        assert events[0]['content'] == 'Hello'
        assert events[1]['content'] == 'World'
    
    def test_extract_ndjson_events(self):
        """Тест извлечения NDJSON событий из буфера"""
        self.processor.buffer = "{\"content\": \"Hello\"}\n{\"content\": \"World\"}\n"
        events = self.processor._extract_ndjson_events(final=False)
        assert len(events) == 2
        assert events[0]['content'] == 'Hello'
        assert events[1]['content'] == 'World'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])