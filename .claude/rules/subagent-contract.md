# Subagent Return Contract

Any dispatch via the Agent tool (Explore / Plan / general-purpose) ends its prompt with this
card template, and the result is relayed to the user in card form — never a raw dump of the
agent's transcript. Only fields that apply:

- **What moved** — outcome in 1–2 sentences ("findings only" for read-only agents).
- **Design in one paragraph** — approach + the one non-obvious choice (Plan agents).
- **Files touched / examined** — paths, one line each.
- **Evidence** — exact commands + output verbatim, never "tests pass". (Reality-facing
  acceptance, see `workflow.md`.)
- **Residual / dependencies** — what still needs action outside the task, each with an
  owner (me / user / CI / infra).
- **Outside scope** — adjacent things noticed but not touched.

`/review` presents its findings in the same card shape (see the skill). Residual items with
a recurring ownerless file/topic feed the `/retro` gap scan.
