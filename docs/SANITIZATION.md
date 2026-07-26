# Message sanitization — what it does and whether we need it

Audited 2026-07-26. Recommendation: **turn off**, keep the code as a break-glass.

## Origin

Commit `e29b8dc` (2025-10-08), *filter "done" from openwebui onswer*. A local
openwebui instance was folding the `done` field out of streamed chunks back into
its message history and sending it upstream, where strict providers rejected it.

## What it actually strips

Four keys, nothing else — `MessageSanitizer.SERVICE_FIELDS` in
[src/core/sanitizer.py:12](../src/core/sanitizer.py#L12):

```python
['done', '__stream_end__', '__internal__', 'stream_end']
```

Two independent passes, both gated by the single `SANITIZE_MESSAGES` env var:

**Requests** — [chat_service.py:58-63](../src/services/chat_service/chat_service.py#L58-L63).
Removes those keys from the top level of each `message` dict. Shallow, cheap.

**Streamed responses** — [stream_processor.py:112-187](../src/services/chat_service/stream_processor.py#L112-L187).
Recursively removes them from `choices[]` and `choices[].delta`.

## How often it fires

`logs/app.log` covers 2025-10-18 → 2026-07-26, 1402 streams.

| Log event | Hits |
|---|---|
| `Message sanitization removed N service fields` (requests) | **0** |
| `Stream chunk sanitization completed` (responses) | 60 |

All 60 response-side hits are test runs, not traffic: every one falls in a second
where the log also shows 14–22 concurrent streams — the pytest signature. The one
exception, a lone line at `2026-03-17T22:37:12`, is a manual invocation on the day
commit `b191f3d` was written (the fix for choice-level removal).

**Net: zero hits on real traffic in nine months, in either direction.**

Current providers were checked too — `local/orange` (llama.cpp b1565) emits a
`timings` object but none of the four fields; Kimi emits none.

## What it costs when enabled

The flag does not just add CPU work — it switches the stream off byte-exact
pass-through onto a buffered parse path.

* Per SSE frame: `json.loads` → `copy.deepcopy` → recursive walk → `json.dumps`.
  A single long Kimi answer is ~1388 frames.
* **JSON gets re-serialized.** Measured: enabled produces `"choices": [{"index": 0,`,
  disabled passes the provider's original `"choices":[{"index":0,`. Gateway
  transparency is lost.
* The SSE-comment branch at
  [stream_processor.py:152](../src/services/chat_service/stream_processor.py#L152)
  is only reachable once `\n\n` is already in the buffer, so provider heartbeat
  comments are held back until the next full frame. Transparent mode has no such
  delay.
* The tail flush at
  [stream_processor.py:190](../src/services/chat_service/stream_processor.py#L190)
  appends `\n\n` regardless of the separator the provider used.
* A frame that fails to parse is passed through untouched — so the cleaning is
  best-effort anyway.

## Recommendation

The workaround did its job: cleaning the outbound stream removed the source, and
the inbound pass has caught nothing since. The code default is already `false`
([config_manager.py:23](../src/core/config_manager.py#L23)); only `.env` turns it on.

Disable it, keep `sanitizer.py` and the flag as a break-glass.

If openwebui ever starts contaminating history again, note that the cheap half —
request sanitization — needs no buffering at all. It can be split onto its own
flag and left permanently on without touching the expensive stream path.
