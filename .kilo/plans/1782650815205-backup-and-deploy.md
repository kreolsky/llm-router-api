# Backup & Deploy: nnp-ai-router

**Date:** 2026-06-28
**Type:** Full rebuild (src/ + requirements.txt changed — added `aiosqlite>=0.20.0`)
**Target commit:** `50a4ef3` — fix: hot-reload atomicity, SSE comment \r escape, deep_merge list concat
**Result:** ✅ Deployed successfully

## Server target

| Parameter | Value |
|---|---|
| SSH alias | `ssh docker` |
| Path | `/home/serge/docker/server-ai-api` |
| Container | `server-ai-api-api-1` |
| Backup dir | `~/backups/` on server |

## Task 1: Backup production

Create a timestamped tarball of the entire server directory **excluding logs/**:

```bash
ssh docker "mkdir -p ~/backups && tar czf ~/backups/server-ai-api-$(date +%Y%m%d-%H%M%S).tar.gz --exclude='server-ai-api/logs' -C /home/serge/docker server-ai-api"
```

> **Note:** `--exclude` must come **before** the path argument, otherwise tar ignores it with an error.

Verify backup was created:
```bash
ssh docker "ls -lh ~/backups/server-ai-api-*.tar.gz | tail -1"
```

## Task 2: Deploy code & rebuild

Sync `src/` and `requirements.txt`:

```bash
rsync -av --delete src/ docker:/home/serge/docker/server-ai-api/src/
rsync -av requirements.txt docker:/home/serge/docker/server-ai-api/requirements.txt
```

Rebuild image and recreate container (requires `requirements.txt` change — new dep `aiosqlite`):
```bash
ssh docker "cd /home/serge/docker/server-ai-api && docker compose up -d --build"
```

> **Decision rule:** if `requirements.txt` or `Dockerfile` changed → full rebuild (`--build`).
> If only `src/` changed → `docker compose restart` is sufficient (volume-mounted).

## Task 3: Verify

Wait 5 seconds, then check logs:
```bash
sleep 5 && ssh docker "docker logs server-ai-api-api-1 --tail 30"
```

Expected:
- `Configuration manager initialized`
- `Application startup complete`
- No `Traceback`, `ImportError`, `ModuleNotFoundError`

## Rollback (if needed)

Stop the container, extract backup over the server directory, restart:
```bash
ssh docker "cd /home/serge/docker/server-ai-api && docker compose stop"
ssh docker "tar xzf ~/backups/<BACKUP_FILE> -C /home/serge/docker/"
ssh docker "cd /home/serge/docker/server-ai-api && docker compose restart"
```

## Notes

- `config/` and `.env` on server are authoritative — never overwritten.
- **Full rebuild required**: `requirements.txt` added `aiosqlite>=0.20.0` (new dep for `core/usage_db.py`).
- Backup includes `src/`, `config/`, `data/`, `docker-compose.yml`, `.env`, `Dockerfile`, `requirements.txt`.
- Server's `config/` has different providers and keys than local; `dummy` STT key doesn't work there.

## Lessons learned

- Original plan was classified as code-only, but `requirements.txt` had a new dependency → first attempt (`docker compose restart`) crashed with `ModuleNotFoundError: No module named 'aiosqlite'`.
- **Pre-deploy check:** always diff `requirements.txt` and `Dockerfile` against the server before deciding restart vs rebuild.
- `tar --exclude` must precede the path argument.
