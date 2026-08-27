# Fix the usage-writer wedge after mid-stream client disconnects

Size **M** — one commit, high entanglement (the usage-DB write path is a named
entanglement signal), straight to `dev`, no branch.

Discovered while validating `plans/1787901000000-remove-message-sanitization.md`;
pre-existing (reproduced on the pre-change build via `git stash` + rebuild).

## Decisions

**Symptom.** After a client aborts an SSE stream mid-body (`curl -N … | head`),
every subsequent usage flush silently stops inserting rows. No
`Failed to record usage` (`src/core/usage_db.py:287`, throttled to 1/min — zero matches
in full container logs), no `Usage recording task failed` (`:311`). The event
loop stays healthy: streams serve, `Stream completed` and `Outgoing Response`
are logged, health is 200. `docker restart` restores writes. Reproduced 3×:
twice on the new build, once on the pre-change build.

**Architecture facts** (re-grepped today):

- One global aiosqlite connection: `_connection` at `src/core/usage_db.py:26`,
  opened in `init_db` (`:129`, called from `src/api/main.py:75`), closed only at
  lifespan shutdown (`src/api/main.py:93`). aiosqlite runs a single dedicated thread
  with a serialized queue — one operation that never returns wedges every later
  operation, silently.
- Flush path: `src/api/middleware.py:153` (`finally`) → `schedule_flush`
  (`src/core/usage_db.py:322`) → `_flush_row` (`:248–279`, `execute` + `commit`).
- The DB is WAL (`src/core/usage_db.py:130`) on the `./data` bind mount
  (`docker-compose.yml:10`) under Docker Desktop on macOS. WAL coordination
  uses a mmap'd `-shm` file — the exact place a VFS-level hang can live on
  VirtioFS. `busy_timeout=5000` (`:136`) only turns table-lock waits into
  errors; a hang below the busy handler never surfaces as `SQLITE_BUSY`.
- `/stat/api/*` reads share the same connection (`src/core/usage_db.py:388–640`): both
  the diagnostic probe and the blast radius — a wedged thread hangs the
  dashboard too.

**Root cause is not yet named.** Step 1 captures the thread stack while wedged
(`py-spy dump` inside the running container; `pip install` it ephemerally, no
image change). Expected finding: the aiosqlite thread blocked in a SQLite VFS
call (shm lock / fsync) on the bind mount. The fix branches on the dump.

**Primary fix (expected branch): take WAL off the bind mount.**
`init_db` sets `PRAGMA journal_mode=TRUNCATE` instead of WAL. TRUNCATE converts
the persistent WAL flag in the existing file and uses no shared memory. Brief
EXCLUSIVE locks during commit are fine at one-INSERT-per-request rates, and
host-side `sqlite3 data/usage.db` inspection keeps working (this plan's own
validation and the operator workflow depend on it). Stale `usage.db-wal` /
`usage.db-shm` are removed after a successful conversion (conversion fails if a
host CLI holds the file — close CLI sessions first; on failure log ERROR and
continue in the current mode, loud but not fatal).

**Watchdog regardless of branch.** Silent wedges must never be silent again.
Track the oldest pending flush; a check piggybacked on `schedule_flush` (cheap,
synchronous, no new background task): if the oldest pending flush exceeds
`USAGE_FLUSH_STUCK_TIMEOUT` (env, default 30 s), log ERROR with pending count
and swap in a fresh connection. The old connection gets a best-effort close
bounded by a short timeout; an abandoned wedged thread leaks one fd — bounded,
rare, accepted (`INVARIANT:` note in code).

**Tests.** A new api test aborts a stream mid-body (httpx stream, early
close), then asserts a usage row lands for a follow-up request via the
`/stat/api` summary. It reproduces the wedge on this Mac pre-fix and must never
fail post-fix; on other hosts it may not reproduce, which is fine. Unit tests
pin the watchdog (fake wedged connection: detection, ERROR log, swap) and the
journal-mode pragma.

## Risks

- The diagnosis may exonerate WAL/VFS (stack shows something else). Then step 2
  is NOT applied — record the stack in the ticket and re-plan; only the
  watchdog (step 3) ships, as mitigation.
- `journal_mode=TRUNCATE` conversion requires exclusive access; a left-open
  host CLI makes startup conversion fail. Mitigated: loud ERROR + keep current
  mode; the operator closes the CLI and restarts.
- Watchdog swap races an in-flight flush holding the old connection reference
  (`:245` captures it at start): the racing flush is abandoned to its own
  timeout and logged. Accepted — at worst one row is lost loudly.
- Losing WAL costs reader/writer concurrency for host inspection during write
  bursts. One INSERT per request; negligible.

## Order

1. **Diagnose** (no code; capture verbatim into the PR body): reproduce the
   wedge (`curl -N … stream … | head -3`, then a non-stream request, then
   `sqlite3 data/usage.db 'select max(id) from usage_events'` shows no new row).
   While wedged: (a) `curl /stat/api/users` — hanging confirms the shared
   thread is stuck; (b) `py-spy dump --pid 1` in the container. Branch on the
   stack: VFS/shm/fsync → continue; anything else → only step 3–4, re-plan 2.
2. **WAL off**: `init_db` (`src/core/usage_db.py:130`) sets `journal_mode=TRUNCATE`,
   logs the resulting mode, deletes `data/usage.db-wal`/`-shm` after
   successful conversion.
3. **Watchdog** in `usage_db.py`: pending-flush age tracking around
   `schedule_flush`/`_flush_row`, stuck check inside `schedule_flush`, ERROR
   log + bounded-close connection swap, `USAGE_FLUSH_STUCK_TIMEOUT` via
   `ConfigManager`-style env read (module-level, read once — matches the
   `_ENV_SETTINGS` ARCH in `src/core/config_manager.py:14`).
4. **Tests**: `tests/unit/test_usage_db_watchdog.py` (new); api test in
   `tests/api/test_chat_completions.py` or a sibling file
   (`test_usage_writer_survives_aborted_stream`).
5. **Docs**: README env table row for `USAGE_FLUSH_STUCK_TIMEOUT`; `ARCH:` /
   `INVARIANT:` markers in `usage_db.py`; `SYSTEMS.md` regen only if the
   `SYSTEM:` marker text changes.

## Not doing

- Not moving the DB to a named volume or container-local path — it breaks the
  host `sqlite3 data/usage.db` inspection the workflow relies on. Revisit only
  if step 1 shows TRUNCATE also hangs.
- Not building a queue/worker indirection over aiosqlite — single-writer is
  already the design; the wedge sits below aiosqlite.
- Not touching the gemini/mini and deepseek/flash upstream availability
  failures seen in the api suite (separate, environmental).

## Validation

- Pre-fix repro evidence (already captured 3×) quoted in the PR; post-fix the
  exact repro ×5, each followed by a row in `select max(id)`, verbatim.
- Dashboard reads (`/stat/api/users`) responsive during and after the repro.
- Full `tests/unit/` + `tests/api/test_chat_completions.py` + the new tests,
  then a repeat run for ordering (high entanglement). Known environmental
  failures — `gemini/mini` (upstream model retired), `deepseek/flash` (flaky)
  — are expected to stay identical.
- `.claude/scripts/pre-commit-gates.sh` run UNPIPED.
- Live drive on the rebuilt container: aborted stream → follow-up non-stream
  request → `sqlite3` shows both rows; a completed usage-bearing stream
  (`stream_options: {"include_usage": true}`) still records tokens.
