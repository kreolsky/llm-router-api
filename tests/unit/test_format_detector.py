import pytest
from src.services.chat.format_detector import StreamFormatDetector

class TestStreamFormatDetector:
    def test_sse_detection_with_data(self):
        assert StreamFormatDetector.detect('data: {"test": true}') == 'sse'
    
    def test_sse_detection_with_comment(self):
        assert StreamFormatDetector.detect(': comment line') == 'sse'
    
    def test_ndjson_detection(self):
        assert StreamFormatDetector.detect('{"test": true}') == 'ndjson'
    
    def test_invalid_defaults_to_sse(self):
        assert StreamFormatDetector.detect('invalid json') == 'sse'
    
    def test_is_sse_helper(self):
        assert StreamFormatDetector.is_sse('data: test')
        assert not StreamFormatDetector.is_sse('{"json": true}')
    
    def test_is_ndjson_helper(self):
        assert StreamFormatDetector.is_ndjson('{"json": true}')
        assert not StreamFormatDetector.is_ndjson('data: test')