---
category: silent-failure
systems: [model-capabilities]
---

# A round-trip test must feed every shape the producer emits, not the happy one

## What happened

The ext router fills its capabilities cache from the main router's `/v1/models`. The fix
that made ext keep main's `reasoning` block (62c24da) shipped with a green `/review` and a
round-trip test, `test_round_trip_main_renderer_through_ext_normalizer`
(`tests/unit/test_model_capabilities.py`), written specifically to bind main's renderer to
ext's normalizer. After the deploy, ext still served `glm/flash` with no reasoning at all —
its cache entry was `{}` — and nothing was logged.

The test seeded main's cache with `{"context_length": 131072, "supported_parameters":
["reasoning"]}`. On prod, main has NO cache entry for `glm/flash` (it sits behind z.ai, a
generic upstream whose `/models` carries no metadata):

```
glm/flash {"supported": true, "effort_levels": ["low", "high", "max"]} | cache: null
```

So main renders that model with only its `reasoning` block, `_is_openrouter_shape`
(`src/core/model_capabilities/normalizers.py`) found none of `context_length` /
`top_provider` / `architecture` / `pricing`, and the entry fell through to the
generic-empty normalizer. Fixed in 14ed0af (a top-level `reasoning` dict qualifies).

## Root cause

The fixture was taken from the happy cache: a model with rich OpenRouter metadata. The
producer (`ModelService.list_models` → `render_capabilities`) has several input classes —
a rich OpenRouter entry, a llama-server `meta` entry, and NO entry at all (generic upstream)
— and the rendered shape differs per class. The test bound the two components on one class
only, so it proved the path that already worked. Review checked that a round-trip test
existed, not which producer inputs it enumerated.

## Actionable rule

A test that binds a producer to a consumer is parametrized over EVERY input class the
producer has — derived from the producer's own dispatch (here: the normalizer shapes plus
"no cache entry"), not picked from the case that motivated the fix. The empty / minimal
input is always one of the cases: it is the one whose rendered shape carries the fewest
detection signals.

```python
# wrong — one hand-picked, metadata-rich cache entry
cache.upsert("glm/flash", {"context_length": 131072, "supported_parameters": ["reasoning"]},
             source="test")

# right — every class main can hold for a model, including none at all
@pytest.mark.parametrize("cached", [
    None,                                                      # generic upstream (z.ai)
    {"context_length": 131072},                                # llama-server meta
    {"context_length": 131072, "supported_parameters": ["reasoning"],
     "pricing": {"prompt": 1e-7}},                             # OpenRouter-rich
])
async def test_round_trip_main_renderer_through_ext_normalizer(cached): ...
```

Owner: `tests/unit/test_model_capabilities.py` (`TestNormalizeOpenRouter` round trip).
