# Kimi stream stall on long responses

Investigated 2026-07-26. **Resolved** — `kimi` provider now routes through SOCKS5.

## Symptom

Long streaming requests to `kimi` return the first part of the answer, then stop.
No error, no `[DONE]` — the stream just goes silent. Short requests work fine.
Persisted for months.

## Root cause

**The network path to `api.moonshot.ai` is throttled, not Kimi and not our code.**

The connection carries roughly 15–20 KB of response body, then the stream freezes
completely. About 150 s later the remote side closes TCP without finishing the
chunked body, which surfaces as:

```
peer closed connection without sending complete message body (incomplete chunked read)
```

Short answers fit inside that budget and complete normally. Long ones never do.

## Evidence

All runs used the same ~300-word prompt against `kimi-k2.7-code`.

| Setup | Result |
|---|---|
| Router, `SANITIZE_MESSAGES=true`, no proxy | 80 chunks, 21.5 KB, stalled 154 s → incomplete chunked read |
| Router, `SANITIZE_MESSAGES=false` (transparent), no proxy | 19 chunks, 19.7 KB, stalled 155 s → same error |
| **Direct** to `api.moonshot.ai`, router bypassed entirely | died after ~1.4 s of stream, silence until client read timeout |
| Short prompt, router, no proxy | OK — 58 chunks, 15.2 KB, `[DONE]` in 2.8 s |
| Router **via `socks5://proxy.red:1331`** | OK — 1388 chunks, 357 KB, `[DONE]` in 37 s |

Two conclusions follow directly:

* the direct-to-Moonshot run reproduces the stall with the router out of the
  picture, so the gateway is not involved;
* `SANITIZE_MESSAGES=false` (pure pass-through, no buffering in
  `StreamProcessor`) changes nothing, so SSE buffering is not involved either.

## Fix

`config/providers.yaml`:

```yaml
  kimi:
    type: openai
    base_url: https://api.moonshot.ai/v1
    api_key_env: KIMI_API_KEY
    proxy: socks5://proxy.red:1331
```

Same proxy `openrouter` already uses. Requires the `httpx[socks]` extra, which is
already in `requirements.txt`.

Server `config/` is authoritative and is never touched by deploy — this line must
be added there by hand, see [DEPLOY.md](DEPLOY.md).

## Ruled out

* **Brotli SSE decoding.** Known to break streams on `api.moonshot.cn`, which
  sends `Content-Encoding: br`. We use `.ai`, and httpx without the `brotli`
  package never advertises `br`. Observed responses had no `Content-Encoding`.
* **`STREAM_READ_TIMEOUT` (300 s).** It is an httpx read timeout and resets on
  every chunk. The stall happened well inside it, and upstream closed first.
* **SSE frame concatenation / `\n\n` buffering in `StreamProcessor`.** Disproved
  by the transparent-mode run above.

## Notes for future debugging

* `docker compose restart` does **not** re-read `.env`. Use `docker compose up -d`,
  and verify with `docker compose exec api printenv <VAR>`.
* Kimi is a reasoning model: it streams `delta.reasoning_content` before
  `delta.content`. A client that renders only `content` shows a long silence that
  looks like a stall but is not one. Worth checking before blaming the network.
