# Remove message sanitization

## Decisions

`SANITIZE_MESSAGES` defaults to false and is unset in `.env`, so both sanitizing
passes are dead on prod. The flag is read at `src/core/config_manager.py:56` and
gates the request pass at `src/services/chat_service/chat_service.py:61` and the
stream body selected at `src/services/chat_service/stream_processor.py:154`.

Removing the flag removes far more than the flag. `_sanitizing`
(`src/services/chat_service/stream_processor.py:217`) is the ONLY caller of the
SSE frame parser — `_decode_chunks` (`:255`), `_split_frame` (`:285`),
`_iter_sse_frames` (`:312`) and their constants (`:237-244`). The live path
`_passthrough` (`:190`) forwards raw bytes and never decodes. So "UTF-8 split
recovery at chunk boundaries" and "`\r\n\r\n` separator support", advertised at
`README.md:189` and `CLAUDE.md:35`, do not execute on any served request today.
The docs are corrected to match, not the code: nothing has reported a split-
character defect while the parser sat unreachable.

`_capture_usage_from_chunk` (`:335`), `_remap_reasoning_in_chunk` (`:348`) and
`duplicate_reasoning_field` (`:17`) stay — all three are on `_passthrough` or on
the non-streaming path (`chat_service.py:110`).

`StreamProcessor` keeps its `config_manager` argument: it is also the source of
`stream_read_timeout` elsewhere, so the constructor signature does not change.
`_StreamStats` stays; only its `sanitized` counter (`:253`) goes.

`docs/SANITIZATION.md` is deleted rather than updated — it is a 2026-07-26 audit
of a feature that will no longer exist; git history keeps the story.

Line numbers below are from the audit; re-grep the symbol before each edit.

## Risks

- Deleting the frame parser deletes the only code that could heal a split
  multi-byte character. Mitigation: it is already unreachable, so this changes
  no served behaviour — but the drive below must show Cyrillic streaming intact.
- `src/core/header_policy.py` is a hot-path file whose denylist rationale cites
  the sanitizer as a reason the body is re-serialized (`:8` and `:30`). Only the
  word goes; `model override` remains a true reason and the denylist itself must
  not be touched.

## Order

1. Delete the sanitization path and the frame parser it fed.
   - `src/core/sanitizer.py` (whole file, incl. its `SYSTEM: sanitizer` marker at
     `:2`), and its import at `chat_service.py:12` and `stream_processor.py:13`.
   - `chat_service.py:60-74` — the `if self.config_manager.should_sanitize_messages:`
     block inside `_guard_service_errors`; the `async with` and everything from
     `if request_body.get("stream", False):` onward stay, dedented by one level.
   - `stream_processor.py`: `_live_sanitization_flag` (`:101`), `_sanitizing`
     (`:217`), `_sanitize_sse_message` (`:379`), `_decode_chunks` (`:255`),
     `_split_frame` (`:285`), `_iter_sse_frames` (`:312`), the constants
     `_SEPARATORS` / `_DEFAULT_SEPARATOR` / `_LARGE_BUFFER_WARN` /
     `_MAX_UTF8_CHAR_BYTES` (`:237-244`), `_StreamStats.sanitized` (`:253`), the
     `body = ... if should_sanitize else ...` selection (`:154-155`), the
     `sanitization_enabled` log field (`:151`) and the sanitized/transparent
     branch of the completion line (`:182`). `process_stream` then always uses
     `_passthrough`.
   - `config_manager.py:56` (`self.sanitize_messages`), `:65` (the log field),
     `:221-222` (`should_sanitize_messages`). `_env_bool` stays — still used by
     `model_cache_enabled`.
   - Remove every import the deletions made unused (anti-mirage check).
2. Cut the tests down to the surviving surface.
   - `tests/unit/test_sanitizer.py` — whole file.
   - `tests/unit/test_stream_processor.py`: `make_processor` (`:28`) loses its
     `sanitize` parameter and becomes `make_processor()`; every call site drops
     the argument. These sections die WHOLE, including the ones whose names do
     not say "sanitize" — they only ever exercised the frame parser:
     `TestSanitizationMode` (`:65`), `TestSseBoundaryParsing` (`:118`),
     `TestUtf8SplitHandling` (`:147`), `TestSseCommentLines` (`:181`),
     `TestLiveSanitizationFlag` (`:246`), `TestRemainingBuffer` (`:333`), and the
     deferred import block at `:428` with `TestSplitFrame` / `TestIterSseFrames` /
     `TestDecodeChunks`. In `TestReasoningFieldDuplication` (`:358`) only
     `test_sanitized_stream_remapped` (`:403`) goes; the rest stays.
     `TestTransparentMode`, `TestFormatError`,
     `TestConcurrentStreamUsageIsolation`, `TestStatsEnrichment` and
     `TestOpenProviderStream` stay green untouched.
   - `tests/unit/test_config_manager.py:350-365` — the three
     `should_sanitize_messages` cases.
3. Sync the docs and the env surface to the code.
   - `README.md`: `:36` (How It Works step 5 — say raw pass-through, no
     re-framing), `:166` (drop the `sanitizer.py` structure line), `:177` (drop
     "optional sanitization"), `:189` (drop UTF-8 split + `\r\n\r\n` claims),
     `:194` (drop the whole Message sanitization bullet), `:67` (drop the word
     `sanitizer` from the transport rationale, keep `model override`).
   - `CLAUDE.md`: rewrite the **Streaming** paragraph (`:35`) and delete the
     **Message Sanitization** paragraph (`:39`).
   - `src/core/header_policy.py:8` and `:30` — same one-word correction as
     `README.md:67`.
   - `.env`: drop the `SANITIZE_MESSAGES` block. `docs/SANITIZATION.md`: delete.
     `tests/README.md:48`: drop the sanitization phrases from the
     `test_stream_processor.py` row.
   - Regenerate `SYSTEMS.md` (`python3 .claude/scripts/systems-index.py --write`)
     — the `sanitizer` row disappears; `pre-commit-gates.sh` blocks on drift.

## Not doing

- Reintroducing UTF-8 split healing on the passthrough path. It has been absent
  from every served request and nothing reported a defect; adding it now would
  be new work justified by nothing.
- Touching `_remap_reasoning_in_chunk`, `_capture_usage_from_chunk`,
  `duplicate_reasoning_field`, or any entry of the header denylist itself.

## Validation

Full `tests/unit/` plus `tests/api/test_chat_completions.py` (entanglement high:
the SSE path is a boundary crossing), then a repeat run for stream ordering.
`.claude/scripts/pre-commit-gates.sh` run UNPIPED.

Live drive after `docker compose up -d --build`, output captured verbatim:

1. Streaming with Cyrillic (multi-byte, the case the deleted parser claimed to
   protect): `curl -N -X POST localhost:8777/v1/chat/completions -H 'Authorization: Bearer dummy' -H 'Content-Type: application/json' -d '{"model":"local/chat","stream":true,"messages":[{"role":"user","content":"Перечисли пять городов России"}]}'`
   — frames render readable Cyrillic and end with `data: [DONE]`.
2. Non-streaming on the same model — 200 with a normal body.
3. A stream on `local/reasoner` — `reasoning_content` still duplicated, proving
   the passthrough remap survived.
4. `sqlite3 data/usage.db 'select model_id,total_tokens,stream from usage_events order by id desc limit 3'`
   — usage still captured from the streamed response.
