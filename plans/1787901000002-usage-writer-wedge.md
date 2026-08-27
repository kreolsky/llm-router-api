# Stop losing usage rows to host-side SQLite access on the dev Mac

Size **M** — one commit, medium entanglement (usage-DB write path, no code on the
request path changes), straight to `dev`, no branch.

## Decisions

**The bug, named.** Usage rows silently stop persisting after anyone opens
`data/usage.db` from the macOS host (`sqlite3 data/usage.db …`) while the
container runs. Nothing hangs: the aiosqlite worker thread is idle, `/stat/api/*`
answers in ~30 ms over the same connection (`src/core/usage_db.py:182`), the
INSERT and COMMIT in `_flush_row` succeed, and no error is ever logged. The rows
are visible only to the app's own connection and are gone at the next restart.

**Mechanism.** `init_db` opens the DB in WAL (`src/core/usage_db.py:128`) on the
`./data` bind mount (`docker-compose.yml:10`). WAL coordination goes through the
mmap'd `-shm` file, which Docker Desktop's VirtioFS does not share between host
and container. The host CLI therefore believes it is the only client, and on exit
checkpoints and truncates the WAL under the live connection. Everything the app
commits afterwards is invalid for every other reader.

**Evidence** (reproduced in one shot; `app` = `/stat/api/summary`, `fresh` = a new
sqlite connection inside the container):

```
=== after restart:   app=1491 fresh=1491
=== req1:            app=1492 fresh=1492
--- host `sqlite3 data/usage.db 'select count(*)'` → 1492
=== req2:            app=1493 fresh=1492      ← divergence starts here
after a restart:     app=1492 fresh=1492      ← row 1493 lost
```

**Fix: make host access structurally impossible.** `./data:/app/data` becomes a
named volume, with a one-time copy of the existing `./data` contents into it.
Discipline ("do not run sqlite3 on the host") is not a fix — the previous
investigation broke writes with its own measurement command. Inspection moves to
`docker compose exec api python3 -c "import sqlite3 …"` and `/stat/api/*`.

**The volume name is pinned, not derived.** The `volumes:` block declares
`name: nnp-ai-router_usage_data` explicitly, so it no longer depends on the
compose project name. Otherwise a renamed directory or a `-p` flag silently
mounts a different, empty volume and the router starts on an empty DB while every
command still reports success.

**Not a production bug.** On the Linux deploy host a bind mount is the same
inode and WAL/shm behave; this is a Docker Desktop artifact. So the fix is in
`docker-compose.yml`, not in `usage_db.py`, and `journal_mode` stays WAL.

**Marker placement.** The rule that keeps this fixed is enforced by the compose
volume, not by any Python line, so the `INVARIANT(data-loss):` goes on the volume
line in `docker-compose.yml`. The stale `WHY:` at `src/core/usage_db.py:129-133`
— which claims `busy_timeout=5000` protects against "the sqlite3 CLI during an
inspection", now known to be false on this mount — is rewritten as a `WHY:`
stating that only the container process opens the file, pointing at the compose
marker.

**No tests.** The diff is compose + comments + docs; there is no runtime surface
a pytest case could bind. Acceptance is the live drive in `## Validation`.

## Risks

- **Server history.** The deploy host keeps its bind mount and is unaffected on
  Linux. If this repo's `docker-compose.yml` is ever synced to the server, the
  server's `./data` is orphaned and the whole usage history disappears silently —
  migrate the server's volume first, or keep the server file on `./data`. The
  README note lands in the same commit.
- The named volume hides the DB from `ls data/`; an operator expecting a host
  file will think stats were wiped. Mitigated by the README inspection recipe.
- The one-time copy must run while the container is stopped, or the copied file
  is the stale pre-divergence snapshot. The step stops it first.
- Rows written since the current divergence started are already lost and are not
  recoverable by this change; the copied file is the authoritative snapshot.
- `data/model_cache.json` moves into the volume too. It is a rebuildable cache;
  the refresh loop repopulates it if the copy is skipped.

## Order

1. **Move the DB off the bind mount** (one commit):
   - `docker-compose.yml:10` → `usage_data:/app/data`, plus a top-level block
     `volumes: { usage_data: { name: nnp-ai-router_usage_data } }` carrying
     `INVARIANT(data-loss):` + `Why:` — the DB file is opened by the container
     process only; a host-side sqlite3 open resets the WAL under the live
     connection over VirtioFS and every later commit is lost.
   - One-time migration, container stopped:
     `docker compose down` → `docker volume create nnp-ai-router_usage_data` →
     `docker run --rm -v "$PWD/data:/src:ro" -v nnp-ai-router_usage_data:/dst
     alpine cp -a /src/. /dst/` → `docker compose up -d --build`.
   - Rename the host copy to `data.pre-volume-backup/` so it cannot be mistaken
     for the live DB; do not delete it, and add it to `.gitignore` — the existing
     `data/` entry (`.gitignore:30`) does not cover the new name.
   - Replace the stale `WHY:` at `src/core/usage_db.py:129-133` per Decisions.
   - README: `README.md:194` and the `USAGE_DB_PATH` row at `README.md:243` gain
     the named-volume note, the two inspection commands and the server warning;
     `CLAUDE.md:55` gains one clause pointing at the compose `INVARIANT:`.

## Not doing

- Not switching `journal_mode` to TRUNCATE/DELETE. It drops the `-shm` file but
  leaves cross-VirtioFS POSIX locking equally unreliable — a different failure,
  not a fix — and it would change production behaviour for a dev-host defect.
- Not adding the stuck-flush watchdog from the superseded version of this plan.
  Nothing is stuck; a flush-age timer would never have fired here.
- Not adding a periodic read-back detector (fresh connection vs the app's
  `max(id)`). The named volume removes the only known trigger; revisit only if
  divergence is observed again.
- Not moving `logs/` or `config/` off their bind mounts — they are plain files
  with no shared-memory coordination.

## Validation

- Migration landed: `docker compose exec api python3 -c "import sqlite3; …"`
  reports the same row count as the pre-migration host file, verbatim.
- Repro attempt post-fix: that same in-container read, then a chat request, then
  the read again — the count increments.
- The trigger is out of reach: `sqlite3 data.pre-volume-backup/usage.db` stays
  frozen while `/stat/api/summary` advances.
- Row survives a restart: request → `docker compose restart api` → still counted.
- `tests/unit/test_usage_db.py` (tmp_path-based, must stay green) plus
  `.claude/scripts/pre-commit-gates.sh` run UNPIPED.
- Live drive on the rebuilt container: one non-stream and one streaming request
  (`-N`, `stream_options: {"include_usage": true}`) each produce a row with
  tokens recorded.
