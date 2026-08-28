# Development Rules — Index

**Two tiers.** `.claude/rules/` is auto-injected every session — only process-wide rules
live there; keep it lean. `.claude/rules-scoped/` is NOT auto-loaded: each file is read on
demand when its path trigger fires (a PreToolUse hook reminds once per session on the first
matching edit). One concept = one file; pointers, not restatement.

## Always loaded (`.claude/rules/`)

- **`workflow.md`** — phase sequence + sizing (commits × entanglement), TDD cycle, **plan
  rules**, review gate, self-review, error-recovery ladder, debugging intake, hard rules,
  auto-lessons. *(Single source of truth for the whole process.)*
- **`documentation.md`** — `ARCH:` / `INVARIANT:` / `WHY:` / `SYSTEM:` / `DEBT:` markers, doc
  tiers, decision-pinning trigger and format, no process provenance in comments.
- **`coding-constraints.md`** — stdlib preference, no over-engineering, deletion test,
  surgical changes, size limits, symbol-removal audits, read-the-entry-file, anti-mirage.
- **`git-strategy.md`** — S/M commit straight to `dev`; branch only for L; pre-merge audit;
  `dev→main` ff-only on explicit request; English-only commit messages.
- **`testing.md`** — what a test must bind, "after a run: propose, don't ask", reports are
  user scenarios (commands live in `rules-scoped/testing-ops.md`).
- **`subagent-contract.md`** — return-card format for Agent-tool dispatches and `/review`.

## On demand (`.claude/rules-scoped/`) — READ BEFORE editing matching paths

| Trigger (files you are about to touch) | Read first |
|---|---|
| Running/debugging any suite, `tests/**` | `testing-ops.md` |
| `src/providers/**` | `providers.md` |
| `src/services/**`, `src/api/**` | `services.md` (+ `testing-ops.md`) |
| `config/**`, `src/core/config_manager.py` | `config.md` |
| `src/core/usage_db.py`, `src/api/stat_page.py`, `/stat` routes | `stat.md` |
| Multi-system feature (Phase 1) | `integration.md` |

**A rule whose trigger is an activity rather than a path cannot live in this tier.** It is
always-loaded, or it is mechanized as a hook, or it is nothing. When a rule keeps being
missed, the next move is a hook, not a firmer sentence.

## Artifacts

- **`plans/`** — every approved plan, named `<epoch-ms>-<slug>.md` by `save-plan.py`; the one
  to implement is whichever the user names. Shape and content rules: `workflow.md` → Plans.
  Overwritten drafts are kept in `plans/superseded/`; plans untouched for 90 days are swept
  into `plans/archive/YYYY-MM/`.
- **`lessons/`** — staging area for rules-in-the-making, written ONLY when something went
  wrong (triggers in `workflow.md` → Auto-lessons); routine successful work produces none.
  A lesson's endpoint is a rule or an in-code marker that links back to it.
  Categorized frontmatter + generated `lessons/INDEX.md`
  (`python3 .claude/scripts/lessons-index.py --write`).
- **`SYSTEMS.md`** — generated subsystem catalog (`systems-index.py --write`); the discovery
  gate's first stop. Aliases in `.claude/systems-aliases.json`.
- **`DEBT:` markers** — the grepable tech-debt ledger (`documentation.md`).

## Gates (`.claude/scripts/`)

`pre-commit-gates.sh` runs them all in a couple of seconds — **run it unpiped before any
push**: `invariant-why`, `systems-index --check`, `func-length`, `debt-ledger`, `ruff-src`.
Each is zero-net-growth against a committed baseline in `.claude/baselines/`; intentional
growth is a `--update` in the same commit with justification. `plan-shape-gate.py`
deliberately does NOT gate the commit — it fires on the plan write and at `/implement`
load, the two moments where a reshape is still free. ruff gates `src/` (rules pinned in
`pyproject.toml`, binary in `requirements-dev.txt`); `tests/` is not covered yet.

  Observation: $ ruff check src/          # 2026-08-27, audit-debt branch, before the fix batch
               Found 26 errors.
               [*] 1 fixable with the `--fix` option (9 hidden fixes can be enabled with the `--unsafe-fixes` option).
               $ ruff check src/          # after: fixes + per-file-ignores + targeted noqa/WHY
               All checks passed!
  Rule:        `ruff check src/` is a BLOCKING pre-commit gate (`ruff-src` in
               pre-commit-gates.sh). The old "~526 findings, advisory only" note described
               the pre-config tree; the explicit pyproject rule set + pinned ruff made it
               false. tests/ (~57 findings) stays out of the gate until linted as its own task.
  File:        .claude/scripts/pre-commit-gates.sh — advisory block replaced by the gate.

## Skills (invoke via `/command`)

- `/implement` — orchestrate the workflow phases (scope → TDD → implement → review → commit).
- `/tdd` — TDD initialization.  `/review` — post-implementation self-review.
- `/retro` — session retrospective and lesson capture.
- `/run-tests` — full suite in Docker.  `/deploy-server` — rsync `src/` + restart the container.
