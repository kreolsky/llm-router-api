"""Unit tests for the configurable passthrough header whitelist."""

import pytest

from src.core.identity_headers import (
    DEFAULT_PASSTHROUGH_HEADERS,
    compile_passthrough_spec,
    match_passthrough,
)


class TestCompileSpec:
    def test_default_spec_used_when_none(self):
        spec = compile_passthrough_spec(None)
        for name in DEFAULT_PASSTHROUGH_HEADERS:
            probe = name[:-1] + "os" if name.endswith("*") else name
            assert match_passthrough(probe, spec) is not None

    def test_empty_list_forwards_nothing(self):
        """An explicit empty list is a valid narrowing, not a fallback to default."""
        spec = compile_passthrough_spec([])
        assert match_passthrough("User-Agent", spec) is None

    def test_config_replaces_rather_than_extends_default(self):
        spec = compile_passthrough_spec(["X-Title"])
        assert match_passthrough("x-title", spec) == "X-Title"
        assert match_passthrough("User-Agent", spec) is None

    @pytest.mark.parametrize("bad", [[""], ["   "], [None], [123], ["*"]])
    def test_malformed_entry_raises(self, bad):
        with pytest.raises(ValueError):
            compile_passthrough_spec(bad)


class TestMatching:
    def test_exact_match_is_case_insensitive_and_recased(self):
        spec = compile_passthrough_spec(["X-Session-Id"])
        assert match_passthrough("x-session-id", spec) == "X-Session-Id"
        assert match_passthrough("X-SESSION-ID", spec) == "X-Session-Id"

    def test_prefix_match_keeps_client_spelling(self):
        spec = compile_passthrough_spec(["x-kilocode-*"])
        assert match_passthrough("X-KILOCODE-TASKID", spec) == "X-KILOCODE-TASKID"
        assert match_passthrough("x-kilocode-mode", spec) == "x-kilocode-mode"

    def test_unlisted_header_is_dropped(self):
        spec = compile_passthrough_spec()
        assert match_passthrough("x-custom", spec) is None
        assert match_passthrough("authorization", spec) is None

    def test_kilo_code_default_header_set(self):
        """Kilo Code (opencode fork) sends these to a generic openai provider."""
        spec = compile_passthrough_spec()
        for name in ("x-session-affinity", "X-Session-Id", "x-parent-session-id", "User-Agent"):
            assert match_passthrough(name, spec) == name
        # OpenRouter-attribution headers are opt-in, not default
        assert match_passthrough("HTTP-Referer", spec) is None
        assert match_passthrough("X-Title", spec) is None
