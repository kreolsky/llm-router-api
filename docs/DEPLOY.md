# Deploy

Remote server: `ssh docker`
Project path: `/home/serge/docker/server-ai-api`
Container: `server-ai-api-api-1`, port 8777 → 8000

No git on server — files synced directly. Volume mount `./src:/app/src`.

## Pre-deploy checklist

Before syncing, always check the server state:

```bash
# Container health
ssh docker "docker logs server-ai-api-api-1 --tail 5"

# Compare requirements.txt — if different, need full rebuild
ssh docker "cat /home/serge/docker/server-ai-api/requirements.txt"
```

## Keep server config

Server configs (`config/`, `.env`) are authoritative and must never be overwritten.
Only sync `src/` for code updates. Never rsync the whole project directory.

## Code-only update (src changes)

```bash
rsync -av --delete src/ docker:/home/serge/docker/server-ai-api/src/
ssh docker "cd /home/serge/docker/server-ai-api && docker compose restart"
```

## Full rebuild (Dockerfile, requirements)

Only when `requirements.txt` or `Dockerfile` changed:

```bash
rsync -av --delete src/ docker:/home/serge/docker/server-ai-api/src/
scp requirements.txt docker:/home/serge/docker/server-ai-api/
scp Dockerfile docker:/home/serge/docker/server-ai-api/
ssh docker "cd /home/serge/docker/server-ai-api && docker compose up --build -d"
```

## Verify

```bash
ssh docker "docker logs server-ai-api-api-1 --tail 15"
```

Check for:
- `Configuration manager initialized` — server configs loaded
- `Application startup complete` — no import/startup errors

## Notes

- API keys on server differ from local — `dummy` key not configured there
- Server keys are in server's `config/user_keys.yaml`
- Server has more providers than local (zai, kimi, orange, embedding, transcriber, agents, etc.)
