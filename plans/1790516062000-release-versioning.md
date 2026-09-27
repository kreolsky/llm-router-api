# Release versioning: tags, release notes, version in /health

## Decisions

- A release is an annotated git tag `vMAJOR.MINOR.PATCH` on the `origin/dev` SHA plus a fast-forward of `origin/main` to that SHA; no file in the tree carries a version. `.claude/rules/git-strategy.md:17` already mandates the fast-forward `git push origin dev:main`; the release skill wraps it.
- Level recommendation by presence of a commit type since the last tag: `BREAKING CHANGE` in a body or `!:` in a subject → major; else any `feat` → minor; else patch. The operator picks the level; the first release is `v1.0.0` by operator ruling (no previous tag).
- Release notes: `docs/release/release-YYYY-MM-DD-vX.Y.Z.md`, written in Russian, H1 `# <Release-in-Russian> vX.Y.Z — YYYY-MM-DD` (the word as in the sibling project's notes), changes grouped by theme from commit bodies, a mandatory upgrade-actions section (rebuild vs restart, new env vars, config keys, usage DB schema). Committed on `dev` BEFORE the tag.
- Release does NOT deploy. Deploy stays the separate `deploy-server` skill (operator ruling).
- The version reaches the running process through a file, because the deploy host has no git and receives `src/` by rsync (`.claude/skills/deploy-server/SKILL.md` step 3a). `deploy-server` writes `git describe --tags --always --dirty` into the remote `src/VERSION` after the rsync and before the restart; a local tree never carries the file, so a local run reports `dev`.
- `src/api/main.py:159` `health_check` returns `{"status": "ok", "version": APP_VERSION}`; `APP_VERSION` is read once at import from `src/VERSION` (restart picks it up — deploy restarts anyway), `"dev"` when absent. Additive field: clients reading `status` are unaffected.
- `src/VERSION` goes into `.gitignore` so a hand-copied file never lands in a commit.
- Pre-flight is a read-only script `.claude/scripts/release-audit.py [--fetch]`: fast-forward check (STOP when `origin/main` has commits `origin/dev` lacks), clean tree, commit-type counts + recommended level since the last tag, `requirements.txt`/`Dockerfile` changed since the last tag (WARN: next deploy is a rebuild), new `Settings` fields in `src/core/config_manager.py` since the last tag (WARN: env var to document), newest release note H1. Exit 1 on any STOP.

## Risks

- A tag pushed on a SHA that is not the audited `origin/dev` tip — signal: `git rev-parse vX.Y.Z^{}` differs from `origin/main` after the push.
- `/health` gaining a field breaks a client doing exact-shape equality — signal: `tests/api/test_connectivity.py` health test fails.
- `rsync --delete` of `src/` removes the remote `VERSION`; the write must come after the rsync — signal: `/health` on the server says `dev` after a deploy.

## Order

1. `feat(release): version tags, release notes, version in /health` — `src/api/main.py` (APP_VERSION + health field), `tests/unit/test_health_version.py`, `.gitignore` (`src/VERSION`), `.claude/scripts/release-audit.py`, `.claude/skills/release/SKILL.md`, `.claude/skills/deploy-server/SKILL.md` (write VERSION, report it, verify via `/health`), `README.md` (`/health` line + Releases section), `CLAUDE.md` (one line under Configuration pointing at the release skill).

## Not doing

- Automatic deploy on release.
- CHANGELOG.md aggregation; the per-release notes are the changelog.
- A version in `pyproject.toml` or any packaging metadata.

## Validation

- `.venv/bin/python -m pytest tests/unit/ -q` green, including `test_health_version.py` (file absent → `dev`, file present → its stripped content, `/health` body carries it).
- Local drive: `docker compose restart api && curl -s localhost:8777/health` → `{"status":"ok","version":"dev"}`; then `echo v0.0.0-test > src/VERSION && docker compose restart api && curl -s localhost:8777/health` → version `v0.0.0-test`; remove the file and restart.
- `python3 .claude/scripts/release-audit.py --fetch` prints the checks and exits 0 on the prepared `dev`.
