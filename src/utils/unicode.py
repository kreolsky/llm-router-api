"""Unicode escape sequence decoding for provider error messages."""
import json
import re

_UNICODE_PATTERN = re.compile(r'\\u([0-9a-fA-F]{4})')


def decode_unicode_escapes(text):
    """Decode \\uXXXX escape sequences in text from provider APIs.

    Provider APIs return errors in mixed encodings, so multiple strategies
    are tried: JSON roundtrip for objects, codec for plain strings,
    regex fallback for everything else.
    """
    if not text:
        return text

    try:
        if '\\u' in text:
            # WHY: JSON objects with \u escapes decode cleanly via json roundtrip
            if text.startswith('{') and text.endswith('}'):
                decoded = json.loads(text)
                if isinstance(decoded, dict):
                    return json.dumps(decoded, ensure_ascii=False)
            # WHY: plain strings with \u escapes decode via Python's unicode_escape codec
            return text.encode().decode('unicode_escape')
    except (json.JSONDecodeError, ValueError, UnicodeError):
        pass

    # WHY: fallback regex for texts where neither JSON parse nor codec works
    def replace_unicode(match):
        hex_code = match.group(1)
        try:
            return chr(int(hex_code, 16))
        except ValueError:
            return match.group(0)

    return _UNICODE_PATTERN.sub(replace_unicode, text)
