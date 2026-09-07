"""Unit tests for src/services/reasoning_dialect.py — funnel translation."""

import pytest
from fastapi import HTTPException

from src.services.reasoning_dialect import (
    DEFAULT_REASONING_DIALECT,
    REASONING_DIALECTS,
    resolve_dialect,
    translate_reasoning_fields,
    validate_reasoning_dialect,
)

BASE_PROVIDER = {"type": "openai", "base_url": "https://x.example"}
OPENROUTER = {**BASE_PROVIDER, "reasoning_dialect": "openrouter"}
DEEPSEEK = {**BASE_PROVIDER, "reasoning_dialect": "deepseek"}


def _body(**extra):
    """A chat-completions-shaped body with the dsh reasoning fields spliced in."""
    return {"model": "m", "messages": [{"role": "user", "content": "hi"}], **extra}


# ===================================================================
# validate_reasoning_dialect / resolve_dialect
# ===================================================================

class TestDialectResolution:

    @pytest.mark.parametrize("dialect", REASONING_DIALECTS)
    def test_known_dialects_validate(self, dialect):
        validate_reasoning_dialect(dialect)  # no raise

    @pytest.mark.parametrize("dialect", ["openai-compatible", "DeepSeek", "", 3, None])
    def test_unknown_dialect_raises_config_error(self, dialect):
        with pytest.raises(HTTPException) as exc_info:
            validate_reasoning_dialect(dialect, provider_name="p")
        assert exc_info.value.status_code == 500
        assert "reasoning_dialect" in str(exc_info.value.detail)

    @pytest.mark.parametrize("dialect", REASONING_DIALECTS)
    def test_resolve_returns_known_dialect(self, dialect):
        assert resolve_dialect({"reasoning_dialect": dialect}) == dialect

    def test_absent_key_resolves_to_default(self):
        assert resolve_dialect(BASE_PROVIDER) == DEFAULT_REASONING_DIALECT == "openai"

    @pytest.mark.parametrize("provider_config", [None, {}, {"reasoning_dialect": "bogus"}])
    def test_defensive_read_falls_back_to_default(self, provider_config):
        """The funnel re-reads tolerantly: mocked configs bypass the
        construction-time validation (same defensive pattern as the effort
        policy's request-path re-check)."""
        assert resolve_dialect(provider_config) == "openai"


# ===================================================================
# openai dialect (the default)
# ===================================================================

class TestOpenAIDialect:

    def test_thinking_dropped_effort_kept(self):
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning_effort="high"), BASE_PROVIDER)
        assert out["reasoning_effort"] == "high"
        assert "thinking" not in out
        assert "reasoning" not in out

    def test_malformed_thinking_dropped_too(self):
        """The dialect has no `thinking` field: dropping it whatever its shape
        is the translation, not a mutation of client data."""
        out = translate_reasoning_fields(_body(thinking="yes"), BASE_PROVIDER)
        assert "thinking" not in out

    def test_body_without_fields_unchanged(self):
        body = _body(temperature=0.2)
        assert translate_reasoning_fields(body, BASE_PROVIDER) == body


# ===================================================================
# deepseek dialect — the native wire shape, identity
# ===================================================================

class TestDeepSeekDialect:

    def test_both_fields_kept_verbatim(self):
        body = _body(thinking={"type": "enabled"}, reasoning_effort="max")
        assert translate_reasoning_fields(dict(body), DEEPSEEK) == body

    def test_title_shaped_request_passes_untouched(self):
        """A title turn carries `thinking: {type: disabled}` only — the native
        dialect forwards it as-is."""
        body = _body(thinking={"type": "disabled"})
        assert translate_reasoning_fields(dict(body), DEEPSEEK) == body


# ===================================================================
# openrouter dialect — re-nesting
# ===================================================================

class TestOpenRouterDialect:

    def test_effort_re_nests_and_originals_are_gone(self):
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning_effort="high"), OPENROUTER)
        assert out["reasoning"] == {"effort": "high"}
        assert "reasoning_effort" not in out
        assert "thinking" not in out

    def test_max_maps_to_high(self):
        """dsh spells `max`; OpenRouter's effort vocabulary tops out at `high`."""
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning_effort="max"), OPENROUTER)
        assert out["reasoning"] == {"effort": "high"}

    @pytest.mark.parametrize("effort,expected", [("low", "low"), ("medium", "medium")])
    def test_shared_vocabulary_verbatim(self, effort, expected):
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning_effort=effort), OPENROUTER)
        assert out["reasoning"] == {"effort": expected}

    def test_unknown_effort_passes_through_verbatim(self):
        """INVARIANT: the translation never gates — unknown spellings ride on
        for the upstream to judge (the 400-gate is the effort policy's)."""
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning_effort="ultra"), OPENROUTER)
        assert out["reasoning"] == {"effort": "ultra"}

    def test_off_maps_to_disabled(self):
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning_effort="off"), OPENROUTER)
        assert out["reasoning"] == {"enabled": False}

    def test_title_shaped_request_becomes_enabled_false(self):
        """The title turn: `thinking: {type: disabled}` only — must translate
        (not error) into OpenRouter's disabled spelling."""
        out = translate_reasoning_fields(_body(thinking={"type": "disabled"}), OPENROUTER)
        assert out["reasoning"] == {"enabled": False}
        assert "thinking" not in out

    def test_enabled_without_effort_becomes_enabled_true(self):
        out = translate_reasoning_fields(_body(thinking={"type": "enabled"}), OPENROUTER)
        assert out["reasoning"] == {"enabled": True}

    def test_effort_without_thinking_still_re_nests(self):
        """A bare client may send only the top-level effort; the re-nest does
        not depend on the thinking toggle being present."""
        out = translate_reasoning_fields(_body(reasoning_effort="low"), OPENROUTER)
        assert out["reasoning"] == {"effort": "low"}

    def test_disabled_wins_over_a_declared_effort(self):
        out = translate_reasoning_fields(
            _body(thinking={"type": "disabled"}, reasoning_effort="high"), OPENROUTER)
        assert out["reasoning"] == {"enabled": False}
        assert "effort" not in out["reasoning"]

    def test_pre_existing_reasoning_keys_survive_the_merge(self):
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning_effort="high",
                  reasoning={"max_tokens": 512}), OPENROUTER)
        assert out["reasoning"] == {"max_tokens": 512, "effort": "high"}

    def test_enabled_adds_no_flag_beside_a_nested_effort(self):
        """Effort already declared in the nested dialect implies enabled —
        no redundant `enabled: true` is merged in."""
        out = translate_reasoning_fields(
            _body(thinking={"type": "enabled"}, reasoning={"effort": "low"}), OPENROUTER)
        assert out["reasoning"] == {"effort": "low"}
        assert "enabled" not in out["reasoning"]

    def test_malformed_thinking_left_in_place(self):
        """A malformed toggle is client garbage: it rides on for the upstream
        to refuse — the translation neither interprets nor hides it. The
        well-formed effort beside it is still re-nested."""
        out = translate_reasoning_fields(
            _body(thinking={"type": "maybe"}, reasoning_effort="high"), OPENROUTER)
        assert out["thinking"] == {"type": "maybe"}
        assert out["reasoning"] == {"effort": "high"}
        assert "reasoning_effort" not in out

    def test_non_dict_reasoning_blocks_translation(self):
        """A string `reasoning` leaves nowhere safe to write — body unchanged."""
        body = _body(thinking={"type": "enabled"}, reasoning_effort="high",
                     reasoning="garbage")
        assert translate_reasoning_fields(body, OPENROUTER) == body

    def test_body_without_fields_unchanged(self):
        body = _body(temperature=0.2)
        assert translate_reasoning_fields(body, OPENROUTER) == body
