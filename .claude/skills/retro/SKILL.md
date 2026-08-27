---
name: retro
description: Session retrospective. Ретро, ретроспектива сессии, итоги, уроки.
---

# Session Retrospective

Phase 5. Auto-lessons triggers live in `.claude/rules/workflow.md` — don't restate.

## 1. Summary
Accomplishments this session; bugs encountered, fixes, and root causes.

## 2. Extract lessons
Write a lesson only if a `workflow.md` Auto-lessons trigger fired (3+ fix iterations on one
category · new architectural pattern · non-obvious workflow optimization). Otherwise skip to 4.

## 3. Write lesson (if triggered)
- Check `lessons/INDEX.md` for an existing lesson on the topic — update, don't duplicate.
- `lessons/YYYY-MM-DD-short-slug.md`: What happened · Root cause · Actionable rule · Code example (wrong vs right).
- **Frontmatter is mandatory**: `category:` (one of the taxonomy in
  `.claude/scripts/lessons-index.py` `CATEGORIES` — the single home; propose a new category
  only when none fits, adding it there in the same change) + optional `systems: [...]`
  (`SYSTEMS.md` names).
- Regenerate the index: `python3 .claude/scripts/lessons-index.py --write`.
- Integrate the rule into the matching `.claude/rules/` file (only if not already covered); update `RULES.md` if a new rule file is created. Subject to the evidence gate in 3a.

## 3a. Evidence gate — no harness edit without an observation

Any edit to the harness itself — `CLAUDE.md`, `.claude/rules/**`, `.claude/rules-scoped/**`,
`.claude/skills/**`, `RULES.md` — requires this block, emitted in the chat and copied into the
commit body:

```
Observation: <verbatim tool output / error / user message that this session produced>
Rule:        <one sentence, the behaviour change>
File:        <path> — <new rule file | tightened existing line>
```

Constraints:
- **Observation is verbatim and from THIS session.** A paraphrase, a remembered incident, or
  "this seems generally better" is not evidence — without it, propose the edit and stop.
- **One rule per edit.** No bundling unrelated tightenings into one harness change.
- **Tighten before adding.** If an existing line covers the observation, edit that line; a new
  rule file needs the grep that proves no existing file owns the seam (same proof `workflow.md`
  demands for a "new dir / format / subsystem").
- **A contradiction is a question, not an edit** — a new rule conflicting with an existing
  marker or rule line means stop and ask which is wrong (`documentation.md` → Maintenance).

Why: rules edited on taste drift away from the code and only surface later in
`/reality-audit`. Evidence makes each line traceable to the failure it prevents.

## 3b. Gap scan (only when a lesson was written this session)

A recurring category+system pair means the knowledge keeps landing in lessons because no
rule/script/skill OWNS that seam (an escalation target that appears in no
rule's boundary is an unowned seam).

- Count lessons in `INDEX.md` sharing the new lesson's `category` + a `systems` entry.
- **3+ lessons on one pair** → output a Gap proposal: `category X on system Y has N lessons;
  propose owner: <new scoped rule / addition to existing rule file / script gate / skill>`.
- Proposal only — the user decides. Never auto-create rule files.

## 4. Memory update
Save relevant feedback/project memories (user preferences, validated approaches, decisions).

## 5. Present
Output the summary + any created/updated files. Do NOT commit — the user decides.
