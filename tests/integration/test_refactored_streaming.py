import pytest
from src.services.chat.smart_buffer_manager import SmartStreamBufferManager
from src.services.chat.format_processor import StreamFormatProcessor
from src.services.chat.parsed_event import ParsedStreamEvent

class TestRefactoredStreaming:
    @pytest.mark.asyncio
    async def test_sse_stream_no_double_parse(self):
        manager = SmartStreamBufferManager()
        processor = StreamFormatProcessor()
        
        # Simulate SSE stream
        chunks = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":" World"}}]}\n\n',
            b'data: [DONE]\n\n'
        ]
        
        full_content = ""
        usage = {}
        
        for chunk in chunks:
            events = manager.process_chunk(chunk)
            for event in events:
                # JSON уже распарсен!
                assert event.data is not None or event.raw == 'data: [DONE]'
                
                # Process БЕЗ повторного парсинга
                full_content, usage = processor.process_parsed_event(
                    event, full_content, usage
                )
        
        assert full_content == "Hello World"
        # Для SSE [DONE] событий usage остается пустым, т.к. в SSE нет usage данных
        assert usage == {}
    
    @pytest.mark.asyncio
    async def test_ndjson_stream_conversion(self):
        manager = SmartStreamBufferManager()
        processor = StreamFormatProcessor()
        
        # Simulate NDJSON stream
        chunks = [
            b'{"message":{"content":"Hello"}}\n',
            b'{"message":{"content":" World"}}\n',
            b'{"done":true,"prompt_eval_count":5,"eval_count":10}\n'
        ]
        
        sse_chunks = []
        
        for chunk in chunks:
            events = manager.process_chunk(chunk)
            for event in events:
                sse_chunk = processor.format_ndjson_to_sse(
                    event, "test-model", "req-123"
                )
                if sse_chunk:
                    sse_chunks.append(sse_chunk)
        
        assert len(sse_chunks) == 2  # Два контент-чанка (done не генерирует чанк)
        assert b'data: {"id": "chatcmpl-req-123", "object": "chat.completion.chunk", "created":' in sse_chunks[0]
        assert b'"content": "Hello"' in sse_chunks[0]
        assert b'"content": " World"' in sse_chunks[1]

    @pytest.mark.asyncio
    async def test_buffer_manager_remaining_data(self):
        manager = SmartStreamBufferManager()
        
        # Incomplete SSE chunk
        chunk = b'data: {"choices":[{"delta":{"content":"Partial'
        manager.process_chunk(chunk)
        
        remaining_event = manager.get_remaining_data()
        assert remaining_event.raw == 'data: {"choices":[{"delta":{"content":"Partial'
        assert not remaining_event.is_valid
        assert remaining_event.format == 'sse'

    @pytest.mark.asyncio
    async def test_buffer_manager_utf8_recovery(self):
        manager = SmartStreamBufferManager()
        
        # Simulate a chunk with a broken UTF-8 sequence
        chunk1 = b'data: {"choices":[{"delta":{"content":"\xd0' # Incomplete UTF-8 for 'Р'
        chunk2 = b'\xa0\xd0\x9f"}}]}\n\n' # Completes 'РП'
        
        events1 = manager.process_chunk(chunk1)
        assert len(events1) == 0
        
        events2 = manager.process_chunk(chunk2)
        assert len(events2) == 1
        assert events2[0].content == "РП"