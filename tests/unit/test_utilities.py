"""Unit tests for utility modules: deep_merge, unicode, generate_key."""

import pytest

from src.utils.deep_merge import deep_merge
from src.utils.unicode import decode_unicode_escapes
from src.utils.generate_key import generate_key


# ---------------------------------------------------------------------------
# deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_flat_merge_no_overlap(self):
        result = deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_flat_merge_with_overlap_dict2_wins(self):
        result = deep_merge({"a": 1, "b": 2}, {"b": 99})
        assert result == {"a": 1, "b": 99}

    def test_deep_nested_merge(self):
        dict1 = {"a": {"x": 1, "y": 2}}
        dict2 = {"a": {"y": 20, "z": 30}}
        result = deep_merge(dict1, dict2)
        assert result == {"a": {"x": 1, "y": 20, "z": 30}}

    def test_dict2_overwrites_non_dict_with_dict(self):
        result = deep_merge({"a": "string"}, {"a": {"nested": True}})
        assert result == {"a": {"nested": True}}

    def test_dict1_not_mutated(self):
        dict1 = {"a": {"x": 1}}
        dict2 = {"a": {"y": 2}}
        result = deep_merge(dict1, dict2)
        assert dict1 == {"a": {"x": 1}}
        assert result is not dict1

    def test_empty_dicts(self):
        assert deep_merge({}, {}) == {}
        assert deep_merge({"a": 1}, {}) == {"a": 1}
        assert deep_merge({}, {"b": 2}) == {"b": 2}

    def test_three_level_deep_nesting(self):
        dict1 = {"l1": {"l2": {"l3": "original", "keep": True}}}
        dict2 = {"l1": {"l2": {"l3": "replaced", "new": 42}}}
        result = deep_merge(dict1, dict2)
        assert result == {"l1": {"l2": {"l3": "replaced", "keep": True, "new": 42}}}


# ---------------------------------------------------------------------------
# decode_unicode_escapes
# ---------------------------------------------------------------------------

class TestDecodeUnicodeEscapes:
    def test_none_returns_none(self):
        assert decode_unicode_escapes(None) is None

    def test_empty_string_returns_empty(self):
        assert decode_unicode_escapes("") == ""

    def test_string_without_escapes_returns_as_is(self):
        assert decode_unicode_escapes("hello world") == "hello world"

    def test_json_object_with_unicode_escapes(self):
        raw = '{"error": "\\u041e\\u0448\\u0438\\u0431\\u043a\\u0430"}'
        result = decode_unicode_escapes(raw)
        assert "Ошибка" in result

    def test_plain_string_with_unicode_escapes(self):
        raw = "\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442"
        result = decode_unicode_escapes(raw)
        assert result == "Привет"

    def test_text_with_no_unicode_escapes_unchanged(self):
        text = "No special chars here!"
        assert decode_unicode_escapes(text) == text

    def test_mixed_text_with_unicode_escapes(self):
        raw = "Error: \\u0442\\u0435\\u0441\\u0442"
        result = decode_unicode_escapes(raw)
        assert "тест" in result


# ---------------------------------------------------------------------------
# generate_key
# ---------------------------------------------------------------------------

class TestGenerateKey:
    def test_starts_with_prefix(self):
        key = generate_key()
        assert key.startswith("nnp-v1-")

    def test_hex_part_is_64_chars(self):
        key = generate_key()
        hex_part = key.removeprefix("nnp-v1-")
        assert len(hex_part) == 64
        # Verify it is valid hex
        int(hex_part, 16)

    def test_two_keys_are_different(self):
        assert generate_key() != generate_key()
