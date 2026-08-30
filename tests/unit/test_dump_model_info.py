"""Unit tests for scripts/dump_model_info.py — the model_info.yaml draft printer."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from src.core.model_capabilities import merge_capabilities, normalize_provider_model

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dump_model_info.py"
_spec = importlib.util.spec_from_file_location("dump_model_info", _SCRIPT)
dump_model_info = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dump_model_info)


def _write_cache(tmp_path, payload) -> str:
    path = tmp_path / "model_cache.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _record(raw: dict) -> dict:
    return {"data": normalize_provider_model(raw), "fetched_at": 1700000000.0,
            "source": "openrouter"}


_RAW = {
    "id": "gemini/mini",
    "context_length": 1048576,
    "top_provider": {"max_completion_tokens": 8192, "is_moderated": False},
    "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
    "supported_parameters": ["reasoning_effort", "tools"],
    "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
}


class TestDumpModelInfo:
    def test_draft_reparses_as_the_stored_schema(self, tmp_path):
        """The printed YAML round-trips back to exactly the cached stored form —
        the draft IS the merge input, not a second normalization of it."""
        path = _write_cache(tmp_path, {"gemini/mini": _record(_RAW)})
        entries = dump_model_info.load_entries(path, [])
        draft = yaml.safe_load(dump_model_info.render_draft(entries, path))
        stored = entries["gemini/mini"]["data"]
        assert draft["model_info"]["gemini/mini"] == stored
        # pasting the draft into model_info.yaml is a no-op against the cache
        assert merge_capabilities(stored, draft["model_info"]["gemini/mini"]) == stored

    def test_draft_carries_the_derived_reasoning_flag(self, tmp_path):
        path = _write_cache(tmp_path, {"gemini/mini": _record(_RAW)})
        entries = dump_model_info.load_entries(path, [])
        draft = yaml.safe_load(dump_model_info.render_draft(entries, path))
        assert draft["model_info"]["gemini/mini"]["reasoning"] == {"supported": True}

    def test_selection_filters_and_sorts(self, tmp_path):
        path = _write_cache(tmp_path, {"b/two": _record(_RAW), "a/one": _record(_RAW)})
        assert list(dump_model_info.load_entries(path, [])) == ["a/one", "b/two"]
        assert list(dump_model_info.load_entries(path, ["b/two"])) == ["b/two"]

    def test_unknown_model_is_an_error(self, tmp_path):
        path = _write_cache(tmp_path, {"a/one": _record(_RAW)})
        with pytest.raises(KeyError, match="nope"):
            dump_model_info.load_entries(path, ["nope"])

    def test_empty_capabilities_entry_is_commented_out(self, tmp_path):
        """A model the upstream told us nothing about must not emit an empty
        mapping — that would be an unparseable/meaningless model_info entry."""
        path = _write_cache(tmp_path, {"deepseek/flash": {"data": {}, "fetched_at": 1.0,
                                                          "source": "generic"}})
        entries = dump_model_info.load_entries(path, [])
        rendered = dump_model_info.render_draft(entries, path)
        assert "# deepseek/flash: no capabilities cached" in rendered
        assert yaml.safe_load(rendered)["model_info"] is None
