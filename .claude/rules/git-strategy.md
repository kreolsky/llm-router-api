---
alwaysApply: true
---

# Git Strategy

* **Branch First (large only)**: S and M go straight to `dev` — a branch is earned by needing
  more than ONE commit, and by nothing else. Create a feature branch from `dev` only for L:
  work whose plan's `## Order` carries 2+ commits (`workflow.md` sizing). Never work directly
  on `main`. Why: a branch carrying a single commit pays a merge commit and a pre-merge audit
  for work a direct commit to `dev` would have finished.
* **Base branch**: `dev` holds the latest stable changes. Always branch from `dev`.
* **Pre-merge audit**: `git diff dev <branch> --stat`, review every changed file, get
  confirmation.
* **Release**: sync `dev` to `main` with `git push origin dev:main` (fast-forward) — **only
  when the user explicitly asks**. Never push to `main` automatically after a commit. Do NOT
  create a local merge commit on `main`: it diverges the histories and breaks future
  fast-forward pushes.
* **Clean up**: delete feature branches after merge into `dev`.
* **Foreign working-tree changes stay untouched.** The tree may contain edits that are not
  yours. Never revert, stash, `git checkout --`, reformat or commit them along with your own
  change just because they sit in the same `git status`. If a foreign edit blocks you, say so
  and ask. Same for deletions you did not make: they are deliberate. Why: undoing in-flight
  work destroys uncommitted state that has no history to recover from.
* **Commit messages are English-only — subject AND body, no exceptions**, including when the
  request and the whole chat are in Russian. Conventional-commit form:
  `feat(stat): …`, `fix(provider): …`, `docs(plans): …`.
