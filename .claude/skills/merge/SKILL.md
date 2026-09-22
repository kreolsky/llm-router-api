---
name: merge
description: Merge a feature branch into dev. Мерж, слияние веток, слить в dev, влить ветку, merge branch.
---

# Merge

Only an L branch ever reaches here — S and M commit straight to `dev` (`git-strategy.md`).

## 1. Pre-merge audit

```bash
python3 .claude/scripts/merge-audit.py
```

Read-only. Reports the branch (STOP on `main`/`dev`), whether `/review` recorded THIS tip
(STOP — the branch's only review gate, `workflow.md` → *a commit is a step, not a release*),
whether the branch is behind `origin/dev` (STOP — rebase first), a WARN for an unclean tree,
and the commits and `--stat` the merge would carry. Exit 1 on any STOP.

- Any STOP → resolve it before going on; never merge past one.
- A rebase to clear the freshness STOP **voids the Phase-4 evidence** if it changed code
  (`workflow.md` → *a rebase invalidates acceptance evidence*): re-drive, re-`/review`.
- WARN (unclean tree) → foreign in-flight edits are legitimate and stay untouched; never
  sweep them into this merge.
- Then **halt and ask for explicit confirmation** — the script cannot observe consent.

## 2. Merge

- `rm -f "$(git rev-parse --git-dir)/review-ok"` — the sentinel is consumed by the merge, so
  the next branch cannot inherit it.
- `git checkout dev && git merge --no-ff <branch>`.
- Non-trivial conflicts → halt and ask.

## 3. After

- `git log --oneline -5` to confirm.
- **Do not push.** `dev → main` is ff-only and only on an explicit request
  (`git-strategy.md`).
- Ask before deleting the local branch; delete only on an explicit yes.
