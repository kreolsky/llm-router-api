"""Unit tests for src/services/reasoning_effort.py and its load-time validation."""

from io import StringIO
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.core.config_manager import ConfigManager
from src.services.reasoning_effort import (
    apply_reasoning_effort,
    parse_effort_policy,
)

ERROR_CTX = {"request_id": "req-test", "user_id": "user-test", "model_id": "model/x"}


def _model_config(allowed=("low", "medium", "high"), default="high",
                  param="reasoning_effort", with_options=False):
    """Build a models.yaml-style model entry; None omits that piece."""
    block = {"allowed": list(allowed)}
    if default is not None:
        block["default"] = default
    if param is not None:
        block["param"] = param
    entry = {"provider": "p", "provider_model_name": "x", "reasoning_effort": block}
    if with_options:
        entry["options"] = {"reasoning_effort": "low"}
    return entry


# ===================================================================
# parse_effort_policy
# ===================================================================

class TestParseEffortPolicy:

    def test_valid_block_defaults_param(self):
        policy, reason = parse_effort_policy(
            {"reasoning_effort": {"allowed": ["low", "high"], "default": "low"}})
        assert reason is None
        assert policy == {"allowed": ["low", "high"], "default": "low",
                          "param": "reasoning_effort"}

    def test_absent_key_is_not_an_error(self):
        assert parse_effort_policy({"provider": "p"}) == (None, None)
        assert parse_effort_policy({}) == (None, None)
        assert parse_effort_policy(None) == (None, None)

    @pytest.mark.parametrize("block,fragment", [
        ("not-a-mapping", "not a mapping"),
        ({}, "non-empty list"),
        ({"allowed": []}, "non-empty list"),
        ({"allowed": ["low", 3]}, "non-empty list"),
        ({"allowed": ["low"], "default": "max"}, "must be one of"),
        ({"allowed": ["low"], "default": 3}, "must be one of"),
        ({"allowed": ["low"], "param": "effort"}, "must be one of"),
    ])
    def test_malformed_blocks(self, block, fragment):
        policy, reason = parse_effort_policy({"reasoning_effort": block})
        assert policy is None
        assert fragment in reason

    def test_options_conflict_rejected(self):
        cfg = {"reasoning_effort": {"allowed": ["low"]},
               "options": {"reasoning_effort": "low"}}
        policy, reason = parse_effort_policy(cfg)
        assert policy is None
        assert "options.reasoning_effort" in reason


# ===================================================================
# apply_reasoning_effort — default injection
# ===================================================================

class TestDefaultInjection:

    def test_default_injected_at_top_level_param_only(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        out = apply_reasoning_effort(dict(body), _model_config(), **ERROR_CTX)
        assert out["reasoning_effort"] == "high"
        assert "reasoning" not in out  # only at param's location, never both
        assert out["messages"] == body["messages"]

    def test_default_injected_at_nested_param_only(self):
        body = {"messages": []}
        cfg = _model_config(allowed=("minimal", "full"), default="full",
                            param="reasoning.effort")
        out = apply_reasoning_effort(dict(body), cfg, **ERROR_CTX)
        assert out["reasoning"]["effort"] == "full"
        assert "reasoning_effort" not in out

    def test_nested_param_preserves_existing_reasoning_dict(self):
        body = {"messages": [], "reasoning": {"keep": True}}
        cfg = _model_config(param="reasoning.effort")
        out = apply_reasoning_effort(dict(body), cfg, **ERROR_CTX)
        assert out["reasoning"] == {"keep": True, "effort": "high"}

    def test_no_default_no_injection(self):
        body = {"messages": []}
        out = apply_reasoning_effort(dict(body), _model_config(default=None), **ERROR_CTX)
        assert out == body

    def test_non_dict_reasoning_skips_injection(self):
        """A non-dict `reasoning` value leaves nowhere safe to write."""
        body = {"messages": [], "reasoning": "garbage"}
        cfg = _model_config(param="reasoning.effort")
        out = apply_reasoning_effort(dict(body), cfg, **ERROR_CTX)
        assert out == body


# ===================================================================
# apply_reasoning_effort — allowed client values pass through untouched
# ===================================================================

class TestAllowedClientValues:

    def test_allowed_top_level_value_untouched(self):
        body = {"messages": [], "reasoning_effort": "low"}
        out = apply_reasoning_effort(dict(body), _model_config(), **ERROR_CTX)
        assert out == body
        assert "reasoning" not in out  # no second field in the other dialect

    def test_allowed_nested_dialect_untouched(self):
        body = {"messages": [], "reasoning": {"effort": "medium"}}
        out = apply_reasoning_effort(dict(body), _model_config(), **ERROR_CTX)
        assert out == body
        assert "reasoning_effort" not in out  # never relocated to param's location

    def test_allowed_value_wins_over_default(self):
        body = {"messages": [], "reasoning_effort": "low"}
        out = apply_reasoning_effort(dict(body), _model_config(), **ERROR_CTX)
        assert out["reasoning_effort"] == "low"  # default NOT injected over it

    def test_null_counts_as_absent(self):
        body = {"messages": [], "reasoning_effort": None}
        out = apply_reasoning_effort(dict(body), _model_config(), **ERROR_CTX)
        assert out["reasoning_effort"] == "high"


# ===================================================================
# apply_reasoning_effort — the refused principal
# ===================================================================

class TestRefusedValues:

    def test_value_outside_allowed_is_400(self):
        body = {"messages": [], "reasoning_effort": "max"}
        with pytest.raises(HTTPException) as exc_info:
            apply_reasoning_effort(body, _model_config(), **ERROR_CTX)
        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail["error"]
        assert detail["code"] == 400
        assert detail["metadata"]["error_code"] == "invalid_parameter_value"
        # the message names the allowed list
        assert "low, medium, high" in detail["message"]
        assert "max" in detail["message"]

    def test_disallowed_nested_dialect_is_400(self):
        body = {"messages": [], "reasoning": {"effort": "max"}}
        with pytest.raises(HTTPException) as exc_info:
            apply_reasoning_effort(body, _model_config(), **ERROR_CTX)
        assert exc_info.value.status_code == 400

    def test_disallowed_nested_value_refused_next_to_an_allowed_top_level(self):
        """Both dialects are gated — an allowed value in one location must not
        smuggle a disallowed value in the other one past the gate."""
        body = {"messages": [], "reasoning_effort": "low", "reasoning": {"effort": "max"}}
        with pytest.raises(HTTPException) as exc_info:
            apply_reasoning_effort(body, _model_config(), **ERROR_CTX)
        assert exc_info.value.status_code == 400
        assert "max" in exc_info.value.detail["error"]["message"]

    def test_disallowed_top_level_refused_next_to_an_allowed_nested(self):
        body = {"messages": [], "reasoning_effort": "max", "reasoning": {"effort": "low"}}
        with pytest.raises(HTTPException) as exc_info:
            apply_reasoning_effort(body, _model_config(), **ERROR_CTX)
        assert exc_info.value.status_code == 400

    def test_both_dialects_allowed_passes_through_untouched(self):
        body = {"messages": [], "reasoning_effort": "low", "reasoning": {"effort": "high"}}
        out = apply_reasoning_effort(dict(body), _model_config(), **ERROR_CTX)
        assert out == body

    def test_oversized_value_is_truncated_in_the_message(self):
        """The unvalidated client value is bounded before it reaches the
        envelope and the WARNING log."""
        body = {"messages": [], "reasoning_effort": {"nested": "x" * 500}}
        with pytest.raises(HTTPException) as exc_info:
            apply_reasoning_effort(body, _model_config(), **ERROR_CTX)
        message = exc_info.value.detail["error"]["message"]
        assert "x" * 500 not in message
        assert "..." in message
        assert len(message) < 200

    def test_non_string_value_is_400(self):
        body = {"messages": [], "reasoning_effort": 3}
        with pytest.raises(HTTPException) as exc_info:
            apply_reasoning_effort(body, _model_config(), **ERROR_CTX)
        assert exc_info.value.status_code == 400


# ===================================================================
# apply_reasoning_effort — absent / malformed policy
# ===================================================================

class TestNoPolicy:

    def test_model_without_key_body_identical(self):
        body = {"messages": [], "reasoning_effort": "whatever", "reasoning": {"effort": "x"}}
        cfg = {"provider": "p", "options": {"stream": True}}
        out = apply_reasoning_effort(dict(body), cfg, **ERROR_CTX)
        assert out == body

    def test_empty_model_config_body_identical(self):
        body = {"messages": []}
        assert apply_reasoning_effort(dict(body), {}, **ERROR_CTX) == body

    @pytest.mark.parametrize("cfg_builder", [
        lambda: _model_config(default="max"),          # default not in allowed
        lambda: _model_config(with_options=True),      # options.reasoning_effort conflict
        lambda: _model_config(param="effort"),         # bad param
        lambda: {**_model_config(), "reasoning_effort": "flat"},  # not a mapping
    ])
    def test_malformed_block_means_passthrough(self, cfg_builder):
        """Defensive mirror of the loader: what it drops, the funnel ignores."""
        body = {"messages": [], "reasoning_effort": "max"}
        out = apply_reasoning_effort(dict(body), cfg_builder(), **ERROR_CTX)
        assert out == body  # no 400, no injection


# ===================================================================
# ConfigManager._validate_models — load-time soft validation
# ===================================================================

def _validated_models(models):
    """Run _validate_models over a config dict with the logger captured."""
    with patch("src.core.config_manager.logger") as mock_logger:
        ConfigManager._validate_models({"models": models})
    return models, mock_logger


class TestLoadTimeValidation:

    def test_valid_block_kept(self):
        cfg = _model_config()
        models, mock_logger = _validated_models({"m": cfg})
        assert "reasoning_effort" in models["m"]
        mock_logger.warning.assert_not_called()

    def test_default_not_in_allowed_warned_and_dropped(self):
        cfg = _model_config(default="max")
        models, mock_logger = _validated_models({"m": cfg})
        assert "reasoning_effort" not in models["m"]
        warning = str(mock_logger.warning.call_args)
        assert "ignoring reasoning_effort block" in warning
        assert "must be one of" in warning

    def test_options_conflict_warned_and_dropped(self):
        cfg = _model_config(with_options=True)
        models, mock_logger = _validated_models({"m": cfg})
        assert "reasoning_effort" not in models["m"]
        assert "options.reasoning_effort" in str(mock_logger.warning.call_args)
        assert "options" in models["m"]  # options themselves are untouched

    @pytest.mark.parametrize("block", [
        {"allowed": []},
        {"allowed": ["low", 3]},
        {"allowed": ["low"], "param": "effort"},
        "flat",
    ])
    def test_malformed_blocks_dropped(self, block):
        cfg = {"provider": "p", "reasoning_effort": block}
        models, mock_logger = _validated_models({"m": cfg})
        assert "reasoning_effort" not in models["m"]
        assert mock_logger.warning.called

    def test_unknown_block_keys_warn_only_not_dropped(self):
        cfg = {"provider": "p", "reasoning_effort": {
            "allowed": ["low"], "default": "low", "futur": True}}
        models, mock_logger = _validated_models({"m": cfg})
        assert models["m"]["reasoning_effort"]["allowed"] == ["low"]  # kept
        assert any("unknown keys" in str(c) for c in mock_logger.warning.call_args_list)

    def test_model_without_block_untouched(self):
        cfg = {"provider": "p", "options": {"stream": True}}
        models, mock_logger = _validated_models({"m": cfg})
        assert models["m"] == cfg
        mock_logger.warning.assert_not_called()

    def test_wired_into_load_config(self):
        """_load_config runs _validate_models: a bad block never reaches consumers."""
        file_map = {
            "providers.yaml": "providers:\n  p:\n    type: openai\n    base_url: https://x\n",
            "models.yaml": (
                "models:\n"
                "  m:\n"
                "    provider: p\n"
                "    reasoning_effort:\n"
                "      allowed: [low]\n"
                "      default: max\n"
            ),
            "user_keys.yaml": "user_keys:\n  k:\n    project_name: t\n",
        }

        def _multi_open(path, *args, **kwargs):
            for key, content in file_map.items():
                if path.endswith(key):
                    sio = StringIO(content)
                    sio.__enter__ = lambda s: s
                    sio.__exit__ = lambda s, *a: None
                    return sio
            raise FileNotFoundError(path)

        with patch("builtins.open", side_effect=_multi_open), \
             patch("os.path.exists", return_value=True), \
             patch("src.core.config_manager.logger"):
            cm = ConfigManager.__new__(ConfigManager)
            cm.config_dir = "/fake/config"
            cm.providers_path = "/fake/providers.yaml"
            cm.models_path = "/fake/models.yaml"
            cm.user_keys_path = "/fake/user_keys.yaml"
            cm.model_info_path = "/fake/model_info.yaml"
            config = ConfigManager._load_config(cm, fail_on_error=False)

        assert "reasoning_effort" not in config["models"]["m"]
