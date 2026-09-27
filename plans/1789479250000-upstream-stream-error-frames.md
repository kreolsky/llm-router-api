# Mid-stream upstream error frames: log and record, still forward verbatim

## Decisions

- Current behaviour: `_passthrough` at `src/services/chat_service/stream_processor.py:172-186`
  peeks a chunk only for `b'"reasoning"'` and `b'"usage"'`. A llama-server late failure
  (`data: {"error":{"code":500,"message":"...peg-native format","type":"server_error"}}`,
  then close with no `[DONE]`) is opaque bytes: the router logs `Stream completed |
  status=200` and the usage row is `status_code=200, error_code=NULL, has_usage=0`.
  Incident row `8f67d9fb1b8c9717` (2026-09-15 11:50:08 UTC) reads as a clean success.
- Add a third peek in `_passthrough`, gated on `b'"error"' in chunk`: for each complete
  `data: ` line that parses as JSON with a top-level `error` dict, call one new helper
  `_note_upstream_error(payload, request_id, user_id, model_id, provider_name, req_stats)`.
  The chunk itself is yielded **unchanged, before** the peek runs, same as the usage peek —
  forwarding stays byte-for-byte (the `INVARIANT` below pins it).
- Log through the existing provider error channel `log_provider_error`
  (`src/core/error_handling/error_handler.py:48`): `provider_name`, `error_details` = the
  raw line truncated to 200 chars, `status_code` = `error.code` when it is an int else 0,
  `request_id`, `user_id`, `model_id`. No second logger call site; the message shape is
  the one already grepped for (`Provider '<name>' returned error <code>: ...`).
- Record through `enrich_stats_from_envelope(req_stats, payload,
  default_error_code="provider_stream_error", overwrite=True)`
  (`src/core/error_handling/envelope.py:17`). The upstream frame is the terminal error of
  the request, which is exactly what `overwrite=True` is documented for. `status_code`
  stays 200 — what the client actually got; the dashboard already counts
  `error_code IS NOT NULL` as an error (`src/core/usage_db/queries.py:16-17`).
- `provider_stream_error` is a new error_code literal, distinct from `provider_http_error`
  (status-level refusal before the body) so the dashboard can group the two.
- Peek is best-effort like the other two: a line split across chunks or non-JSON passes
  through untouched and unlogged. Same limitation as the reasoning remap, accepted.
- `_passthrough` gains three parameters (`user_id`, `model_id`, `provider_name`,
  `req_stats`); `process_stream` already holds all of them. If the function crosses the
  50-line gate, the peek block moves whole into `_note_upstream_error` — no baseline bump.

## Risks

- A legitimate delta whose *content* contains the substring `"error"` triggers the
  byte gate; the JSON parse then finds no top-level `error` key and nothing happens. Cost:
  one parse on that chunk. No false log, no false row.
- A provider that sends an `error` frame **and then** continues (none known) would log
  once per frame and the last frame wins the row — acceptable, the row was NULL before.
- `enrich_stats_from_envelope` with `overwrite=True` clears `error_message` when the
  frame has none; the row then carries `provider_stream_error` with NULL message. That is
  the documented invariant of the helper, not a new behaviour.

## Order

1. Tests first in `tests/unit/test_stream_processor.py` (class `TestStatsEnrichment`,
   style of `test_mid_stream_error_writes_error_code_and_partial_usage` at line 229):
   - `test_upstream_error_frame_is_forwarded_verbatim_and_recorded`: chunks = a delta,
     the exact llama-server frame, **no** `[DONE]`; assert the collected bytes equal the
     input bytes exactly (no `[DONE]` synthesized), `stats.error_code ==
     "provider_stream_error"`, `stats.error_message` contains `peg-native`,
     `stats.has_usage is False`.
   - `test_upstream_error_frame_is_logged`: `caplog` at ERROR contains
     `Provider 'p' returned error 500:` and the first 200 chars of the frame.
   - `test_delta_containing_error_substring_is_not_an_error`: a content delta with the
     text `"error"` inside → `stats.error_code is None`, nothing logged at ERROR.
   - `test_error_frame_with_prior_usage_keeps_partial_usage`: usage chunk then error
     frame → usage retained, error_code set (both `finally` and the peek run).
   Run: `python -m pytest tests/unit/test_stream_processor.py --tb=short` — the four
   must fail (first one on `error_code`, log one on caplog).
   Then implement in `src/services/chat_service/stream_processor.py`: the peek in
   `_passthrough` + `_note_upstream_error`; put on the `yield chunk` line:
   `# INVARIANT: the chunk is yielded before any peek and never rewritten by one.
   # Why: the router is transparent — the incident showed the client must see the
   # upstream's own error text and framing, the peeks only log and record.`
   Run `tests/unit/` in full (medium entanglement: touches the SSE hot path and the
   usage row) + `tests/api/test_chat*`; then `.claude/scripts/pre-commit-gates.sh`.
   One commit: `feat(stream): log and record upstream mid-stream error frames`.

## Not doing

- Retries, UTF-8 sanitising, rewriting or translating the upstream error text.
- Synthesizing `data: [DONE]` after an upstream error frame — the client already saw
  the stream close; adding a sentinel the upstream did not send is re-framing.
- Billing tokens for the failed request — the upstream sends no `usage` on this path.
- Anything on orange (llama.cpp parse tolerance, DFlash) — separate task.

## Validation

- Local: fake upstream script from the investigation (scratchpad `rt/fake_upstream.py`,
  serves delta + lone `\xD0` + llama error frame, no `[DONE]`) behind a scratch router on
  `:8778`; `curl -sN` and compare bytes (`==` upstream payload, as in the investigation),
  then show the new `Provider 'fake' returned error 500:` line and the usage row with
  `error_code='provider_stream_error'`.
- Deployed: `rsync src/` + `docker compose restart api`; drive one streaming and one
  non-streaming `local/orange/chat` request through `:8777` (regression only — the real
  frame is not reproducible on demand, 0/10 runs); confirm `/stat/api` still lists rows.
