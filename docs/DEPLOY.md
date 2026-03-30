# Deploy

Remote server: `ssh docker`
Project path: `/home/serge/docker/server-ai-api`
Container: `server-ai-api-api-1`, port 8777 → 8000

No git on server — files synced directly. Volume mount `./src:/app/src`.

## Code-only update (src changes)

```bash
rsync -av --delete src/ docker:/home/serge/docker/server-ai-api/src/
ssh docker "cd /home/serge/docker/server-ai-api && docker compose restart"
```

## Keep server config
Серверные конфиги приоритетны и должны быть сохранены!

## Full rebuild (Dockerfile, requirements)

```bash
rsync -av --delete src/ docker:/home/serge/docker/server-ai-api/src/
scp requirements.txt docker:/home/serge/docker/server-ai-api/
scp Dockerfile docker:/home/serge/docker/server-ai-api/
ssh docker "cd /home/serge/docker/server-ai-api && docker compose up --build -d"
```

## Verify

```bash
ssh docker "docker logs server-ai-api-api-1 --tail 10"
```

## Notes

- API keys on server differ from local — `dummy` key not configured there
- Server keys are in server's `config/user_keys.yaml`
