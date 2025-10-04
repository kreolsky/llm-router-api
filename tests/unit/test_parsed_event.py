import pytest
from src.services.chat.parsed_event import ParsedStreamEvent

class TestParsedStreamEvent:
    def test_sse_content_extraction(self):
        event = ParsedStreamEvent(
            raw='data: {"choices":[{"delta":{"content":"Hello"}}]}',
            format='sse',
            data={"choices":[{"delta":{"content":"Hello"}}]}
        )
        assert event.has_content
        assert event.content == "Hello"
    
    def test_ndjson_content_extraction(self):
        event = ParsedStreamEvent(
            raw='{"message":{"content":"World"}}',
            format='ndjson',
            data={"message":{"content":"World"}}
        )
        assert event.has_content
        assert event.content == "World"

    def test_no_content(self):
        event = ParsedStreamEvent(
            raw='data: {"choices":[{"delta":{}}]}',
            format='sse',
            data={"choices":[{"delta":{}}]}
        )
        assert not event.has_content
        assert event.content == ""
    
    def test_usage_extraction_sse(self):
        event = ParsedStreamEvent(
            raw='data: {"usage":{"prompt_tokens":10,"completion_tokens":20}}',
            format='sse',
            data={"usage":{"prompt_tokens":10,"completion_tokens":20}}
        )
        assert event.usage == {"prompt_tokens":10,"completion_tokens":20}
    
    def test_usage_extraction_ndjson(self):
        event = ParsedStreamEvent(
            raw='{"done":true,"prompt_eval_count":10,"eval_count":20}',
            format='ndjson',
            data={"done":True,"prompt_eval_count":10,"eval_count":20}
        )
        assert event.usage == {"prompt_tokens":10,"completion_tokens":20}
    
    def test_is_done_sse(self):
        event = ParsedStreamEvent(
            raw='data: [DONE]',
            format='sse',
            data={'done': True}
        )
        assert event.is_done
    
    def test_is_done_ndjson(self):
        event = ParsedStreamEvent(
            raw='{"done":true}',
            format='ndjson',
            data={"done":True}
        )
        assert event.is_done

    def test_not_done(self):
        event = ParsedStreamEvent(
            raw='data: {"choices":[{"delta":{"content":"Hello"}}]}',
            format='sse',
            data={"choices":[{"delta":{"content":"Hello"}}]}
        )
        assert not event.is_done

    def test_invalid_event(self):
        event = ParsedStreamEvent(
            raw='invalid raw data',
            format='sse',
            is_valid=False,
            error="parse error"
        )
        assert not event.is_valid
        assert event.content == ""
        assert event.usage is None
        assert not event.is_done