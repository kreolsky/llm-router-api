"""Unit tests for src/core/model_capabilities.py — normalization, rendering, cache."""

import json
import os

import pytest

from src.core.model_capabilities import (
    CapabilitiesCache,
    _format_price,
    merge_capabilities,
    normalize_provider_model,
    refresh_provider_capabilities,
    render_capabilities,
)

# ---------------------------------------------------------------------------
# Price formatting (decision 2 — regression on 4.35e-07)
# ---------------------------------------------------------------------------

class TestFormatPrice:
    def test_scientific_notation_no_exponent(self):
        assert _format_price(4.35e-07) == "0.000000435"

    def test_zero(self):
        assert _format_price(0) == "0"

    def test_plain_decimal(self):
        assert _format_price(0.001) == "0.001"

    def test_string_input(self):
        assert _format_price("0.000000435") == "0.000000435"

    def test_trailing_zeros_stripped(self):
        assert _format_price(0.1000) == "0.1"

    def test_invalid_falls_back_to_zero(self):
        assert _format_price("not-a-number") == "0"


# ---------------------------------------------------------------------------
# render_capabilities (A3)
# ---------------------------------------------------------------------------

class TestRenderCapabilities:
    def test_empty_input_empty_output(self):
        assert render_capabilities({}) == {}

    def test_input_modalities_derive_vision_and_modality(self):
        stored = {
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            }
        }
        out = render_capabilities(stored)
        assert out["supports_vision"] is True
        assert out["architecture"]["modality"] == "text+image->text"

    def test_text_only_not_vision(self):
        stored = {"architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}}
        out = render_capabilities(stored)
        assert out["supports_vision"] is False
        assert out["architecture"]["modality"] == "text->text"

    def test_max_completion_tokens_flat_and_top_provider(self):
        stored = {"context_length": 8192, "max_completion_tokens": 4096, "is_moderated": True}
        out = render_capabilities(stored)
        assert out["max_completion_tokens"] == 4096
        assert out["top_provider"]["context_length"] == 8192
        assert out["top_provider"]["max_completion_tokens"] == 4096
        assert out["top_provider"]["is_moderated"] is True

    def test_missing_pricing_keys_become_zero_strings(self):
        stored = {"pricing": {"prompt": 0.001}}
        out = render_capabilities(stored)
        pricing = out["pricing"]
        # full key set present
        for key in ("prompt", "completion", "request", "image", "web_search",
                    "internal_reasoning", "input_cache_read"):
            assert key in pricing
        assert pricing["prompt"] == "0.001"
        assert pricing["completion"] == "0"
        assert pricing["image"] == "0"

    def test_pricing_no_exponent(self):
        stored = {"pricing": {"prompt": 4.35e-07, "completion": 0.000000435}}
        out = render_capabilities(stored)
        assert out["pricing"]["prompt"] == "0.000000435"
        assert out["pricing"]["completion"] == "0.000000435"

    def test_per_request_limits_null(self):
        out = render_capabilities({"description": "x"})
        assert out["per_request_limits"] is None

    def test_architecture_modality_not_set_when_empty(self):
        stored = {"architecture": {}}
        out = render_capabilities(stored)
        assert "modality" not in out["architecture"]


# ---------------------------------------------------------------------------
# normalize_provider_model (B1)
# ---------------------------------------------------------------------------

class TestNormalizeOpenRouter:
    def test_full_response_to_stored_form(self):
        raw = {
            "id": "google/gemini-2.0-flash-001",
            "name": "Google: Gemini 2.0 Flash",
            "context_length": 1048576,
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
                "tokenizer": "Gemini",
                "instruct_type": None,
            },
            "top_provider": {
                "context_length": 1048576,
                "max_completion_tokens": 8192,
                "is_moderated": False,
            },
            "supported_parameters": ["tools", "temperature", "stream"],
            "pricing": {
                "prompt": "0.0000001",
                "completion": "0.0000004",
                "image": "0.0000258",
                "request": "0",
                "input_cache_read": "0.000000025",
            },
        }
        out = normalize_provider_model(raw)
        # string prices parsed to floats in stored form
        assert out["context_length"] == 1048576
        assert out["max_completion_tokens"] == 8192  # flattened from top_provider
        assert out["is_moderated"] is False
        assert out["architecture"]["input_modalities"] == ["text", "image"]
        assert out["pricing"]["prompt"] == 0.0000001
        assert out["pricing"]["completion"] == 0.0000004
        assert out["supported_parameters"] == ["tools", "temperature", "stream"]
        assert out["name"] == "Google: Gemini 2.0 Flash"

    def test_reasoning_not_translated_from_supported_parameters(self):
        # decision 3: upstream "reasoning" stays out of our reasoning{} block
        raw = {
            "id": "m",
            "context_length": 8192,
            "supported_parameters": ["reasoning", "tools"],
        }
        out = normalize_provider_model(raw)
        assert "reasoning" not in out
        assert "reasoning" in out["supported_parameters"]

    def test_partial_openrouter(self):
        raw = {"id": "m", "context_length": 4096}
        out = normalize_provider_model(raw)
        assert out == {"context_length": 4096}


class TestNormalizeLlamaServer:
    def test_meta_n_ctx_train_to_context_length(self):
        raw = {"id": "dummy", "meta": {"n_ctx_train": 32768}}
        out = normalize_provider_model(raw)
        assert out == {"context_length": 32768}

    def test_prefers_runtime_n_ctx_over_n_ctx_train(self):
        raw = {"id": "dummy", "meta": {"n_ctx": 131072, "n_ctx_train": 262144}}
        out = normalize_provider_model(raw)
        assert out["context_length"] == 131072

    def test_capabilities_multimodal_implies_vision(self):
        # capabilities lives in the entry the normalizer receives (after the
        # refresh task merges it from the native models[] array).
        raw = {
            "id": "dummy",
            "capabilities": ["completion", "multimodal"],
            "meta": {"n_ctx": 131072, "n_ctx_train": 262144},
        }
        out = normalize_provider_model(raw)
        assert out["architecture"]["input_modalities"] == ["text", "image"]
        assert out["context_length"] == 131072

    def test_no_multimodal_capability_no_vision(self):
        raw = {"id": "dummy", "capabilities": ["completion"], "meta": {"n_ctx": 8192}}
        out = normalize_provider_model(raw)
        assert "architecture" not in out
        assert out["context_length"] == 8192

    def test_missing_meta_empty(self):
        raw = {"id": "dummy"}
        # no openrouter shape, no meta -> generic
        assert normalize_provider_model(raw) == {}


class TestNormalizeGeneric:
    def test_deepseek_like_empty(self):
        raw = {"id": "deepseek-v4-flash", "object": "model", "owned_by": "deepseek"}
        assert normalize_provider_model(raw) == {}

    def test_non_dict_input(self):
        assert normalize_provider_model("not a dict") == {}
        assert normalize_provider_model(None) == {}


# ---------------------------------------------------------------------------
# merge_capabilities (B3)
# ---------------------------------------------------------------------------

class TestMergeCapabilities:
    def test_override_wins_top_level(self):
        base = {"context_length": 8192}
        override = {"context_length": 16384}
        assert merge_capabilities(base, override)["context_length"] == 16384

    def test_deep_merge_architecture(self):
        base = {"architecture": {"input_modalities": ["text", "image"], "tokenizer": "X"}}
        override = {"architecture": {"input_modalities": ["text"]}}
        merged = merge_capabilities(base, override)
        # override wins (replaced, NOT concatenated)
        assert merged["architecture"]["input_modalities"] == ["text"]
        # base-only nested key preserved
        assert merged["architecture"]["tokenizer"] == "X"

    def test_lists_replaced_not_concatenated(self):
        base = {"supported_parameters": ["a", "b"]}
        override = {"supported_parameters": ["c"]}
        assert merge_capabilities(base, override)["supported_parameters"] == ["c"]

    def test_none_inputs(self):
        assert merge_capabilities(None, None) == {}
        assert merge_capabilities({"a": 1}, None) == {"a": 1}


# ---------------------------------------------------------------------------
# CapabilitiesCache (B1 — persist / stale-if-error handled by refresh fn)
# ---------------------------------------------------------------------------

class TestCapabilitiesCache:
    def test_persist_and_reload(self, tmp_path):
        path = str(tmp_path / "model_cache.json")
        cache = CapabilitiesCache(path)
        cache.upsert("m1", {"context_length": 8192}, source="openrouter")
        cache.persist()
        assert os.path.exists(path)

        cache2 = CapabilitiesCache(path)
        cache2.load()
        assert cache2.get("m1") == {"context_length": 8192}
        meta = cache2.get_meta("m1")
        assert meta["source"] == "openrouter"
        assert meta["fetched_at"] is not None

    def test_missing_file_no_error(self, tmp_path):
        cache = CapabilitiesCache(str(tmp_path / "absent.json"))
        cache.load()  # must not raise
        assert cache.get("anything") is None

    def test_corrupt_json_ignored(self, tmp_path):
        path = str(tmp_path / "model_cache.json")
        with open(path, "w") as f:
            f.write("{not valid json")
        cache = CapabilitiesCache(path)
        cache.load()  # must not raise
        assert cache.get("anything") is None

    def test_get_meta_absent(self, tmp_path):
        cache = CapabilitiesCache(str(tmp_path / "c.json"))
        assert cache.get_meta("nope") is None

    def test_atomic_write_no_leftover_tmp(self, tmp_path):
        path = str(tmp_path / "model_cache.json")
        cache = CapabilitiesCache(path)
        cache.upsert("m", {"context_length": 1}, source="p")
        cache.persist()
        # final file is valid JSON
        with open(path) as f:
            data = json.load(f)
        assert data["m"]["data"] == {"context_length": 1}
        # no leftover temp files (mkstemp cleans up via os.replace)
        import glob
        leftovers = glob.glob(str(tmp_path / ".model_cache.*.tmp"))
        assert leftovers == []

    @pytest.mark.asyncio
    async def test_concurrent_persist_no_race(self, tmp_path):
        """Multiple workers (caches) persisting the same path must not collide.

        Regression for the cross-worker ENOENT on os.replace when all workers
        wrote the same 'model_cache.json.tmp'. Each write now uses a unique
        mkstemp temp file.
        """
        import asyncio
        path = str(tmp_path / "model_cache.json")

        async def worker(n):
            cache = CapabilitiesCache(path)
            cache.upsert(f"m{n}", {"context_length": n}, source="p")
            # yield to interleave with other workers around the write
            await asyncio.sleep(0)
            cache.persist()

        # 8 concurrent workers writing the same path
        await asyncio.gather(*(worker(i) for i in range(8)))

        # final file is valid JSON (last writer wins; all writes succeeded)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# refresh_provider_capabilities (B1 — matching, single-model fallback, stale-if-error)
# ---------------------------------------------------------------------------

class _FakeProvider:
    def __init__(self, models_data):
        self._models_data = models_data

    async def list_models(self, request_id="unknown"):
        return self._models_data


class _FakeCM:
    def __init__(self, models):
        provider_names = {m.get("provider") for m in models.values() if m.get("provider")}
        self._cfg = {
            "models": models,
            "providers": {p: {"type": "openai"} for p in provider_names},
        }

    def get_config(self):
        return self._cfg


class TestRefreshProviderCapabilities:
    @pytest.mark.asyncio
    async def test_single_model_fallback_for_dummy_placeholder(self, tmp_path, monkeypatch):
        """llama-server lists one model by its path; provider_model_name 'dummy'
        never matches, but with exactly one model it should still be used.
        Vision capabilities live in the native models[] array (merged in)."""
        models = {
            "local/chat": {"provider": "orange", "provider_model_name": "dummy"},
            "local/reasoner": {"provider": "orange", "provider_model_name": "dummy"},
        }
        cm = _FakeCM(models)
        cache = CapabilitiesCache(str(tmp_path / "c.json"))
        path_id = "/path/to/Qwen3.6-27B.gguf"
        upstream = {
            "models": [{"name": path_id, "capabilities": ["completion", "multimodal"]}],
            "data": [{"id": path_id, "meta": {"n_ctx": 131072, "n_ctx_train": 262144}}],
        }

        async def fake_gpi(*a, **k):
            return _FakeProvider(upstream)

        monkeypatch.setattr("src.core.model_capabilities.get_provider_instance", fake_gpi)
        await refresh_provider_capabilities(cm, cache, "orange")

        for mid in ("local/chat", "local/reasoner"):
            data = cache.get(mid)
            assert data["context_length"] == 131072
            assert data["architecture"]["input_modalities"] == ["text", "image"]

    @pytest.mark.asyncio
    async def test_match_by_provider_model_name(self, tmp_path, monkeypatch):
        """Normal match: provider_model_name equals an upstream model id."""
        models = {"deepseek/flash": {"provider": "deepseek", "provider_model_name": "deepseek-v4-flash"}}
        cm = _FakeCM(models)
        cache = CapabilitiesCache(str(tmp_path / "c.json"))
        upstream = {"data": [{"id": "deepseek-v4-flash", "context_length": 262144}]}

        async def fake_gpi(*a, **k):
            return _FakeProvider(upstream)

        monkeypatch.setattr("src.core.model_capabilities.get_provider_instance", fake_gpi)
        await refresh_provider_capabilities(cm, cache, "deepseek")

        assert cache.get("deepseek/flash")["context_length"] == 262144

    @pytest.mark.asyncio
    async def test_stale_if_error_keeps_existing(self, tmp_path, monkeypatch):
        """Provider list_models failure must not clear existing cache entries."""
        models = {"local/chat": {"provider": "orange", "provider_model_name": "dummy"}}
        cm = _FakeCM(models)
        cache = CapabilitiesCache(str(tmp_path / "c.json"))
        cache.upsert("local/chat", {"context_length": 32768}, source="orange")

        class _Boom:
            async def list_models(self, request_id="unknown"):
                raise RuntimeError("upstream 502")

        async def fake_gpi(*a, **k):
            return _Boom()

        monkeypatch.setattr("src.core.model_capabilities.get_provider_instance", fake_gpi)
        await refresh_provider_capabilities(cm, cache, "orange")  # must not raise

        # existing entry retained
        assert cache.get("local/chat") == {"context_length": 32768}
