# Testing ops — commands, rebuild semantics, isolation

Read before running or debugging any suite. The judgement rules are in
`.claude/rules/testing.md`; this file is only the mechanics.

## Commands

```bash
python -m pytest tests/unit/ -v              # no external deps
python -m pytest tests/api/  -v              # needs the service on :8777
python -m pytest tests/ -v                   # everything
python -m pytest tests/unit/test_x.py -v --tb=line   # targeted (the S-size default)
```

Use the project venv (`.venv/bin/python -m pytest …`) when one exists — a stale system
`httpx` has already made 62 unit tests fail on a `proxy=` kwarg the container supports.
Dev-only deps live in `requirements-dev.txt`, never in `requirements.txt`.

`/run-tests` runs the full set, bringing the container up and waiting for `/health` first.

## Docker

* **The image copies source at build time.** `docker compose up -d --build` after ANY code
  change, or you are testing the previous build. There is no bind mount for `src/`.
* Ports: the container listens on `8000`; compose maps host `8777` → `8000`. Clients and the
  whole test suite talk to `8777`.
* `docker compose logs -f nnp-ai-router` for the request bookends.
* Health: `curl -s http://localhost:8777/health`.
* Never `docker compose down -v` — it destroys the `data/` volume carrying the usage DB and
  the model cache (a PreToolUse hook blocks it).

## Live drive (Phase-4 acceptance)

Green tests are not acceptance. Drive the affected flow against the running container and
paste the output verbatim:

```bash
# non-streaming
curl -s -X POST http://localhost:8777/v1/chat/completions \
  -H "Authorization: Bearer <key from config/user_keys.yaml>" -H "Content-Type: application/json" \
  -d '{"model":"...","messages":[{"role":"user","content":"ping"}],"max_tokens":10}'
# streaming — frames on the wire, NOT a log line
curl -s -N -X POST http://localhost:8777/v1/chat/completions … -d '{… ,"stream":true}'
# refused principal — the half that is usually skipped
curl -s … -H "Authorization: Bearer <key WITHOUT access to that model>"
```

A config change is driven across an actual hot reload (edit the YAML, wait the interval,
re-request) — not by asserting the loader in isolation.
