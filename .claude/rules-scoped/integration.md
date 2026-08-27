# Integration protocol (Phase 1 — L, or any feature touching 3+ systems)

Before implementing:

1. Read `CLAUDE.md` — identify the affected systems.
2. Find them in `SYSTEMS.md`, then `grep -rn "SYSTEM:" src/` and READ each entry file.
3. `grep -rn "ARCH:" src/` in the affected areas — architectural decisions.
4. `grep -rn "INVARIANT:" src/` — constraints that must be preserved.
5. `config/` — are new YAML keys needed? (`rules-scoped/config.md`)
6. `src/core/error_handling/error_types.py` — is a new `ErrorType` needed?
7. Name, in one line each: what the change looks like at the **middleware**, **auth**,
   **service**, **provider** and **response/stream** layers — or why a layer is N/A.

Output the filled list. Skip reasons are part of the output, not an omission.
