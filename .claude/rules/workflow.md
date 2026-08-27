---
alwaysApply: true
---

# Workflow (mandatory)

Single source of truth for: phase sequence, sizing, TDD cycle, review gate, self-review,
error recovery, debugging intake, auto-lessons. Other files point here — do not restate.

## Phases — required sequence

Skipping a phase = hard-rule violation.

**Two axes, and they answer different questions.** Commits decide how much PROCESS;
entanglement decides how much PROOF. **Neither counts files.**

| Size | Criteria — commits | Branch | Phases |
|------|--------------------|--------|--------|
| **S** Quick Fix | ONE commit, low entanglement | no — straight to `dev` | 0 → 3 → 5 |
| **M** Feature | ONE commit, medium or high entanglement — it moves a contract | no — straight to `dev` | 0 → 3 → 4 → 5 |
| **L** Epic | the plan's `## Order` carries 2+ commits | yes, from `dev` | 0 → 1 → 2 → 3 → 4 → 5 |

| Entanglement | Tests | Model |
|--------------|-------|-------|
| **low** (e≤2) | what this diff can break **+ adjacent**, `--tb=line` | Haiku |
| **medium** (3–6) | full `tests/unit/` + the `tests/api/` files the diff touches | Sonnet |
| **high** (≥7) | full `tests/` **+ a repeat run** (races, stream ordering, pool lifecycle) | **Opus** |
| any, but **L** | the above, plus a green full suite before the merge | per e |

**Size is not file count.** It is answered by two questions, in this order:

1. *Does this need more than one commit?* If yes — it needs a plan whose `## Order` says
   so, and that is the ONLY thing that earns a branch. One commit never does: a branch
   carrying a single commit pays the merge and the pre-merge audit for nothing.
2. *How much must be held at once to not break it?* Entanglement — a boundary crossing on
   the request path (middleware → auth → service → provider → upstream → SSE back), an
   `INVARIANT:` on the path, the httpx pool / semaphore lifecycle, the usage-DB write, the
   config hot-reload. Low → **S**; medium and high → **M**; and it sets the test regime and
   the model per the second table — regardless of file count.

Counting files measures the process, not the work: a fix plus its test plus its plan file
is three files, so the old "≤3 files may go straight to dev" rule tripped on every change
that was properly tested. Optional tooling: `.claude/scripts/size-estimate.py` (advisory).

- **Phase 0 — Scope.** State S/M/L and the entanglement signals. The `━━━ SCOPE ━━━` banner
  is recommended, not mandatory; the sizing judgement behind it is required.
  **Discovery gate (also fires in plan/discussion mode, before any design):** look the
  task's nouns up in `SYSTEMS.md` (generated catalog: name · desc · entry file · aliases
  incl. Russian), then `grep -rn "SYSTEM:" src/` filtered to the matched names, then READ
  the entry file of each match. Any "new module / new config key / new provider type /
  new endpoint" proposal MUST cite the grep that proves it does not already exist.
  Building ON an existing mechanism → read its `SYSTEM:` entry file; do not infer its
  contract from one signature or one regex (`coding-constraints.md`).
- **Phase 1 — Integration checklist** (L only). Condensed form is fine: one line
  `affected systems: ___` plus skip reasons. Full form in
  `.claude/rules-scoped/integration.md` when 3+ systems are touched.
- **Phase 2 — TDD as a GATE** (L only). Failing tests BEFORE implementation. S and M still
  write tests — what L adds is the red run as a gate. Never read this as "S/M may skip
  testing": the tests are what makes committing straight to `dev` safe.
- **Phase 3 — Implement.** Run tests after each logical step; breadth from the entanglement
  table, commands in `.claude/rules-scoped/testing-ops.md`. Add `ARCH:`/`INVARIANT:`/`WHY:`
  markers (`documentation.md`). If you add/rename/remove/move a `SYSTEM:` marker,
  regenerate `SYSTEMS.md` (`python3 .claude/scripts/systems-index.py --write`) and commit
  it — `pre-commit-gates.sh` blocks on drift.
- **Phase 4 — Review** (M/L; S only when a Review-gate trigger fires). Auto-invoke
  `/review` — do not ask. Present findings, wait for approval.
  **Acceptance is reality-facing:** for any change with a runtime surface, "done"
  additionally requires driving the affected flow live — a real request through the running
  container (`curl` against `:8777`, streaming included) — and capturing the observed
  evidence verbatim. Green tests are necessary, not sufficient. A streaming change is driven
  with `-N` and the frames are shown; an auth change is driven with BOTH an allowed and a
  REFUSED key; a config change is driven across an actual hot reload. Exemption: diffs
  touching only tests/docs/config with no runtime surface — state the exemption explicitly.
  **Acceptance is PROPORTIONAL and on S it stops early.** For an S diff, targeted tests over
  what the diff can break plus `pre-commit-gates.sh` ARE the acceptance. Explicitly NOT owed
  on an S: a full-suite run, a before/after baseline capture, a prod-vs-dev comparison.
  Select test files by "what could this diff break", never by "what mentions the noun".
- **Phase 5 — Commit & Retro.** Commit only when the user asks. `/retro` runs only when an
  Auto-lessons trigger fired this session — otherwise skip it.

## TDD cycle

1. **Understand** — restate current vs expected behaviour + the code paths. Get confirmation.
   A wrong cause baked into a plan survives every later turn.
2. **Write failing tests** — run them; all must fail for the right reasons.
3. **Review from tests** — adjust the approach based on what writing them revealed.
4. **Implement** — run new + existing tests after each step.
5. **Review vs plan** — missed edge cases, incomplete guards.
6. **Fix rounds** (2–3) — the suite after each.
7. **Impact check** — no regressions in related systems.

Never modify an existing test to make failing code pass.

## Plans

**Plans are ALWAYS written in English** — the entire file, every heading and body line,
regardless of the language of the request. Only the short chat summary may be in Russian.

**Approved plans land in `plans/`**, named `<epoch-ms>-<slug>.md` by `save-plan.py` (the
PostToolUse hook on ExitPlanMode). The timestamp is the directory's only ordering — a plan
named by slug alone cannot be placed in time. Plans untouched for 90 days are swept into
`plans/archive/YYYY-MM/` on the next approval. There is no "active plan" pointer: the plan
to implement is the one the user names.

**A plan has ONE shape, and it is small** — enforced by `plan-shape-gate.py` (the Write|Edit
hook reports it, `/implement` refuses an off-shape plan), not by remembering this section.
Exactly these sections, under exactly these names, max 120 lines:

```
# <title>
## Decisions   — why the chosen thing is shaped this way
## Risks
## Order       — numbered steps, each one a commit (2+ steps ⇒ L ⇒ branch; see sizing)
## Not doing   — consciously ruled out; comes back only as a fresh task
## Validation  — how Phase-4 acceptance is driven live; omit only for a no-runtime-surface diff
## Progress    — only for multi-session work; the resume point
```

Write to 120. The gate only fires at 150, and that 30-line gap is slack, not budget: a plan
that lands a little over gets SPLIT on judgement, never shaved line-by-line to pass the
check. Past 150 the task is too big to plan. No decision IDs (`D7`, `F0`): needing a
cross-reference registry means the document stopped being an instruction.

**Understanding changed ⇒ delete the file and write it again; never append.** The previous
version is kept for you in `plans/superseded/` by `plan-snapshot.py`, so a later post-mortem
reads a diff instead of someone's memory.

**A decision touching existing behaviour carries a `file:line` that resolves** —
gate-checked, fabricated citations fail. A citation cannot be written without opening the
file, and opening the file is the point.

**Planning does not begin until the CURRENT behaviour is named with its `file:line`.** Not
the desired end state — the line that produces today's behaviour and has to change.

**A plan is an instruction to an executor, not a record of the thinking.** It contains ONLY
what will be built; a rejected alternative is DELETED, not kept as a `Why:`, a `## Context`
or a research appendix. The executor cannot tell a live constraint from a dead one, and the
discarded version is in git history, which is where history belongs. **Tests are the plan** —
on a known surface a test list replaces prose entirely.

**No plan for a one-file prose/config edit.** When the expected diff is wording in a single
doc, prompt or YAML file and no code changes, make the edit and drive it — do not write a
plan. The plan is the surface an invented requirement lands on.

## Review gate

Self-initiate `/review` — never wait to be asked, never auto-fix. Trigger when ANY holds:

- The change is **M or L** (S is reviewed only via the triggers below).
- New module / new provider type / new endpoint / cross-cutting change.
- **Hot-path touch regardless of diff size** — danger, not volume:
  `src/core/auth.py`, `src/core/config_manager.py`, `src/providers/base.py`,
  `src/services/chat_service/stream_processor.py`, `src/core/usage_db.py`,
  `src/api/middleware.py`, `config/user_keys.yaml`.
- User says "done", "ready", "push", "задеплой", or asks for a commit.

**No file-count trigger.** Size decides depth; the hot-path list decides danger.

Flow: complete work → `/review` → present findings + fix plan → wait for approval → only
then fix. Any auth/access surface gets a security review however small it looks, and a
change spanning access levels is reviewed at EVERY layer, not just the one it was written in.

**Decision-pinning check** during review (`documentation.md`): a bugfix in a
repeatedly-regressing area MUST add/tighten an `INVARIANT:`/`ARCH:`/`WHY:` marker on the
line that broke, with a `Why:`. Flag any new `INVARIANT:` lacking a `Why:`, and any marker
contradicting the user's latest stated rule (stop and ask which is wrong).

## Self-review (M and L; on S only if the diff surprised you)

1. `git diff --stat` — only expected files changed.
2. Full diff — incomplete guards, duplicated literals, formatting, config-schema drift.
3. Grep old names after renames.
4. Walk a request through the affected path: middleware → auth → service → provider →
   response, streaming AND non-streaming.
5. Tests last.

## Error recovery — escalate per failed attempt

1. **Retry** — re-read the error; check types/imports/signatures. Max 3.
2. **Instrument** — add logging, reproduce, read actual output before coding another fix. Max 2.
3. **Pivot** — step back; propose a simpler approach. Do NOT implement without approval.
4. **Stop** — write up tried/observed/hypotheses to `lessons/`, ask for guidance.

## Hard rules (non-negotiable)

- **Credentials are IN THE PROJECT — read them, never ask.** API keys, the stat key and the
  rest live in `.env` and `config/user_keys.yaml`. Stopping the task to request one of these
  is a hard-rule violation: grep the config first. Only a secret genuinely absent from all
  of them is worth asking for — and then name where you looked.
- **The container copies source at build time.** `docker compose up -d --build` after any
  code change, or you are testing the old code. See `.claude/rules-scoped/testing-ops.md`.
- **Impact assessment**: ask how a change affects providers, services and the config schema
  before implementing.
- **Debugging intake (meta-rule)** — on any bug report, in order:
  1. `git status` first, unconditionally: in-flight changes ARE the running code.
  2. Vague report ("не работает / пусто / сломалось") → ask ONE batched question for the
     missing specifics (exact request, model, streaming or not, provider, first-vs-Nth,
     regression-vs-never-worked) BEFORE reproducing. A stack trace or exact error text in
     the report counts as the specificity. "Minimize questions" applies to implementation
     hand-holding, NOT to debugging — one targeted question saves 10+ blind tool calls.
  3. Name your #1 hypothesis AND its falsifier. An observation you ALREADY have that
     falsifies it ⇒ DROP the hypothesis. If your repro WORKS while the user reports broken,
     the next message is a question to the user, not another investigation step.
  4. "Missing/refused for key X / model Y" = a gating condition (access list, model
     registry, `if not FLAG`) — locate it with one grep; reserve live reproduction for
     runtime-behaviour bugs.
  5. Glance at `lessons/INDEX.md` — the category matching the symptom class may already
     hold the diagnosis.
  6. **Observe before patch**: for a streaming/timing/pool bug, instrument and reproduce
     before writing any fix. Code analysis alone yields plausible-but-wrong hypotheses.
  7. **Diagnose from the client's RENDERED payload, never a log line.** A log line
     `json.dumps`es and escapes; what the client receives is the SSE frame on the wire.
     Reproduce with `curl -N` before theorizing about what a downstream harness "sees".
  8. **Fix #2 in the same area normalizes the class — it does not add another `if`.** If
     the breaking inputs have more than two members, the fix is a projection over them.
- **Subagent dispatches** (Agent tool) follow `subagent-contract.md`.
- **Cheap gates run BEFORE the commit**: `.claude/scripts/pre-commit-gates.sh`. Run it
  **UNPIPED** — `gates | tail -2 && git commit` reads the pipeline's LAST stage, so `tail`
  returns 0, the chain continues and a red gate ships while "BLOCKED" sits in the output.
- **Post-refactor verification**: full unit suite after any refactoring, and a live drive of
  one streaming and one non-streaming request.

## Auto-lessons

Create `lessons/YYYY-MM-DD-short-slug.md` when ANY holds:

- 3+ fix iterations on the same issue category.
- A production escape: a defect reached the deployed router past a green `/review` — the
  lesson must name which review check missed it.
- A new architectural pattern established (a new provider capability, a new marker class).
- A non-obvious workflow optimization discovered.

Structure: frontmatter (`category:`, `systems:`) · What happened · Root cause · Actionable
rule · Code example (wrong vs right). Regenerate the index:
`python3 .claude/scripts/lessons-index.py --write`.

**A lesson is a staging area, not a home.** Its endpoint is a rule (or an in-code marker)
plus a pointer back for the story. A lesson no rule cites is read by nobody: when writing a
new one, check whether it supersedes an existing lesson and delete that one rather than
stacking. Rules never restate a lesson's contract — they link it.

Integrate the rule into the relevant `.claude/rules/` file — but only through the evidence
gate: **no edit to `CLAUDE.md`, `RULES.md`, `.claude/rules{,-scoped}/**` or
`.claude/skills/**` without an `Observation / Rule / File` block whose Observation is
verbatim output from the current session.** No evidence ⇒ propose the edit and stop.
