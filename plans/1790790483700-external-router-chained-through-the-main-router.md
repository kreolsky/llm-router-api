# External router chained through the main router

## Decisions

- Topology: external client → `server-ai-api-ext` (host `docker`, `/home/serge/docker/server-ai-api-ext`, port 8778) → main router `http://api.ai.gray/v1` (= `server-ai-api`, port 8777) → providers. The ext instance holds NO provider credentials of its own; its only upstream is the main router. Verified: `docker exec server-ai-api-ext` reaches `http://api.ai.gray/health` → `{"status":"ok","version":"v1.0.1"}`.
- Current behaviour to change: ext `config/providers.yaml` connects directly to `deepseek`, `zai-code`, `embedding`, `embedding-giga` with its own keys in ext `.env` (`DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `ORANGE_API_KEY`), so main's usage stats never see external traffic.
- Main router gets ONE new key `external` in `/home/serge/docker/server-ai-api/config/user_keys.yaml`; usage rows land under project `external`. `allowed_models`: `glm/pro`, `glm/flash`, `deepseek/flash`, `embeddings/giga/480m`, `stt/gigaam`, `stt/gigaam/big`. `allowed_endpoints`: `/v1/chat/completions`, `/v1/embeddings`, `/v1/audio/transcriptions`, `/v1/models` (routes at `src/api/main.py:207`, `src/api/main.py:214`, `src/api/main.py:221`, `src/api/main.py:178`; endpoint gate at `src/core/auth.py:62`).
- Kill switch = remove the `external` key on main (hot reload ~5s) or stop the ext container; internal keys are unaffected either way.
- Ext `providers.yaml` becomes a single provider `main`: `type: openai`, `base_url: http://api.ai.gray/v1`, `api_key_env: MAIN_API_KEY`, `identity: passthrough`, `reasoning_dialect: deepseek`.
- `reasoning_dialect: deepseek` on the ext hop because the default `openai` dialect drops `thinking` (`src/services/reasoning_dialect.py:14`, default at `src/core/config_schema.py:103`); `deepseek` keeps both fields verbatim so the real per-upstream translation happens once, on main.
- `identity: passthrough` on the ext hop so client harness headers reach main and then z.ai (main's `zai-code` is passthrough); the client's `Authorization` is dropped by the denylist (`src/core/header_policy.py:22`) and replaced with `MAIN_API_KEY`.
- Ext `models.yaml`: `glm/pro`, `glm/flash`, `deepseek/flash`, `embeddings/giga/480m`, `stt/gigaam`, `stt/gigaam/big`, each `provider: main` with `provider_model_name` equal to the same id on main. `glm/pro` keeps its current ext `reasoning_effort` block (`allowed: [low, high, max]`, `default: high`, `param: reasoning_effort`) to preserve xisraa's current default; `glm/flash` and `deepseek/flash` get no block — main's policy gates them.
- `embeddings/qwen3/600m` is removed from ext (models.yaml and both key lists); the `embedding` provider goes with it.
- Ext `user_keys.yaml`: delete `embeddings-client`; add `panda` with a NEW key from `python3 scripts/generate_key.py` (`scripts/generate_key.py:21`), `allowed_models`: `embeddings/giga/480m`, `stt/gigaam`, `stt/gigaam/big`; `allowed_endpoints`: `/v1/embeddings`, `/v1/audio/transcriptions`, `/v1/models`.
- `xisraa` stays on ext with its key unchanged; `allowed_models`: `glm/pro`, `glm/flash`, `deepseek/flash`, `embeddings/giga/480m` (qwen3 dropped, `glm/flash` added); `allowed_endpoints` unchanged.
- Ext `.env`: remove `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `ORANGE_API_KEY`; add `MAIN_API_KEY=<the external key>`; set `DEFAULT_STT_MODEL=stt/gigaam` (today `stt/dummy`, which does not exist on ext). Timeouts/retries already equal on both (`HTTPX_READ_TIMEOUT=60`, `STREAM_READ_TIMEOUT=300`, `OPENAI_TRANSCRIPTION_TIMEOUT=3600`, `PROVIDER_MAX_RETRIES=3`) — leave them.
- Ext code is upgraded to the same code main runs: ext `src/` is an old pre-v1.0.1 tree (no `config_schema.py`, differing auth/middleware/header_policy) that does not know `reasoning_dialect`. `git diff v1.0.1 HEAD -- src` is only `src/__init__.py`, and ext `requirements.txt`/`Dockerfile` equal main's, so a code-only rsync + restart suffices. The old ext `usage.db` is migrated in place by `init_db` (`src/core/usage_db/writer.py:183`).
- Infrastructure-only: no code in this repo changes, so no test suite is owed; acceptance is the live drive in Validation. The only repo artifact is this plan file.

## Risks

- xisraa's `deepseek/flash` changes upstream model: ext mapped it to `deepseek-v4-flash`, main maps it to `deepseek-flash`; and main's effort policy on `deepseek/flash` (`allowed: [low, high]`) now returns 400 on `max`, where ext passed it. Signal: 400 `invalid_parameter_value` in ext logs for xisraa.
- A 429 is retried on both hops (up to 3×3 attempts). Accepted; signal: long latencies on 429 bursts in ext logs.
- Main marks embeddings/stt `is_hidden` (`src/services/model_service.py:123`), so ext's capabilities cache gets no auto-data for them; `/v1/models` on ext still lists them from `models.yaml`. Signal: none needed, cosmetic.
- A wrong key/`base_url` in ext makes startup validation refuse to boot. Signal: `docker logs server-ai-api-ext` + restart loop; rollback from the backups made in Server 1.
- Per-external-user breakdown exists only in ext's own `data/usage.db`; main sees one project `external`.

## Order

1. Commit this plan file to `dev` (`docs(plans): external router chained through main`). Everything after this commit is server-side, not commits, run over `ssh docker` in this sequence:
   - Server 1: Backup: `cp -a config config.bak.<date>`, `cp .env .env.bak.<date>`, `cp -a src src.bak.<date>` in `/home/serge/docker/server-ai-api-ext`; `cp config/user_keys.yaml config/user_keys.yaml.bak.<date>` in `/home/serge/docker/server-ai-api`.
   - Server 2: Main: generate the `external` key, add the `external` entry to `user_keys.yaml`; wait 5s for hot reload; check `curl -s http://api.ai.gray/v1/models -H "Authorization: Bearer <external>"` returns the three chat models.
   - Server 3: Ext code: from a checkout at `v1.0.1`, `rsync -av --delete src/ docker:/home/serge/docker/server-ai-api-ext/src/` (pattern of `.claude/skills/deploy-server/SKILL.md:69`), then write `v1.0.1` into ext `src/VERSION`.
   - Server 4: Ext config: rewrite `providers.yaml`, `models.yaml`, `user_keys.yaml` and `.env` per Decisions (generate the `panda` key); then `docker compose restart` in the ext directory (env changes need the restart).
   - Server 5: Drive Validation; hand the `panda` key to the user.

## Not doing

- Keeping `embeddings/qwen3/600m` anywhere on ext, or re-enabling it on main.
- Per-external-user attribution inside main's stats (one project `external` by design).
- A shared docker network or `host-gateway` — the internal DNS name `api.ai.gray` is used.
- Changing main's `deepseek/flash` mapping or effort policy to match the old ext behaviour.

## Validation

Quick smoke only — per-model coverage, refusals, stats and the kill switch are not driven.

- `curl -s localhost:8778/health` on the server → `"version":"v1.0.1"`; `docker logs server-ai-api-ext --tail 30` has no startup errors.
- Chat: `curl -s localhost:8778/v1/chat/completions -H "Authorization: Bearer <xisraa>" -H "Content-Type: application/json" -d '{"model":"deepseek/flash","messages":[{"role":"user","content":"hi"}]}'` → 200 with a completion.
- Embeddings: `curl -s localhost:8778/v1/embeddings -H "Authorization: Bearer <panda>" -H "Content-Type: application/json" -d '{"model":"embeddings/giga/480m","input":"test"}'` → 200 with a vector.
- STT: `curl -s localhost:8778/v1/audio/transcriptions -H "Authorization: Bearer <panda>" -F model=stt/gigaam -F file=@sample.wav` → 200 with text.
