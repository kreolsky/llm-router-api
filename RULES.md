# Development Rules

Living document. Updated after each session.

## Hard Rules

Non-negotiable. Violation = stop and fix before continuing.

* Branch freshness: Run `git fetch origin && git log HEAD..origin/dev --oneline` before work. Rebase if non-empty.
* Lesson saving: After every session, extract lessons to `lessons/` directory.
* Post-refactor verification: Run full unit test suite after any refactoring.
* Impact assessment: Ask how changes affect providers, services, and config schema before implementation.
* 3+ Iteration Pivot: If a problem requires 3+ iterative fixes, propose a radical architectural simplification.
* Dependency removal audit: `grep -r 'import.*package'` all consumers, verify replacement covers every use case before removing.

## Development Protocol

### TDD Cycle

1. Understand: Restate current behavior, expected behavior, specific code paths. Get user confirmation.
2. Write tests: Design failing tests that define expected behavior. Run them — all should fail.
3. Review from tests: Update approach based on information learned from writing tests.
4. Implement: Write code. Run ALL tests (new + existing) after each logical step.
5. Review vs plan: Compare implementation against plan. Look for missed edge cases, incomplete guards.
6. Fix phases (2-3 rounds): Address issues from review. Full test suite after each fix.
7. Impact check: Verify no regressions in related systems.

### Plan Content (after tests exist)

Tests are the plan. Textual plan includes only:
* Decisions (why, not what)
* Risks (known pitfalls)
* Order (what first, circular dependency awareness)
* Scope (what we're NOT doing)

If `plan_lines / implementation_lines > 2`, the plan is bloated. Cut it.

### Self-Review (after 3+ file changes)

1. `git diff --stat` — verify only expected files changed
2. Full diff review — incomplete guards, duplicated literals, formatting
3. Grep for old names after renames
4. Simulate request flow through affected code paths
5. Run unit tests — last step

## Git Strategy

* **Branch First**: Create feature branch from `dev` for multi-file or non-trivial changes. Minor features (single-concern, ≤3 files) may be committed directly to `dev`. Never work directly on `main`.
* **Base Branch**: `dev` contains latest stable changes. Always branch from `dev`.
* **Pre-Merge Audit**: Run `git diff dev <branch> --stat` and review all changed files. Get user confirmation.
* **Release**: `dev` merged into `main` for production. Never push directly to `main`.
* **Clean Up**: Delete feature branches after merge into `dev`.

## Coding Constraints

* Use standard library and framework built-ins. No custom algorithms when a one-liner exists.
* No over-engineering, no redundant abstractions. Simplest tool for the job.
* No classes unless required for complex state management (providers are the exception — they carry httpx clients and config).
* No nested conditional chains. Use lookup dictionaries and early returns.
* Crash on missing configs/dependencies. No default values for critical data.
* Semantic naming and strict type hints mandatory.
* Extract shared utilities only for genuinely reusable operations.
* All code, comments, docstrings in English.

## Provider Rules

* Every provider must inherit from `BaseProvider` and implement the required interface.
* Provider instances are cached by `(type, base_url)`. Never store request-specific state on instances.
* Format translation happens in the provider, not in the service layer.
* New provider types require: class in `providers/`, registration in `providers/__init__.py`, config entries in `providers.yaml` and `models.yaml`.
* Retry logic lives in the base class. Providers must not implement their own retry.

## Service Layer Rules

* Services validate access BEFORE checking model existence (prevents info leakage).
* Services orchestrate: validate → resolve provider → call provider → return response.
* No direct HTTP calls from services — always go through providers.
* Streaming responses must use `StreamingResponse` with the service's async generator.

## Configuration Rules

* All provider connections, model mappings, and access control defined in YAML. No hardcoded endpoints or model names in code.
* Config changes take effect within the reload interval (default 5s). No restart required.
* Provider cache is cleared on config reload.
* New config fields require: YAML schema update, `config_manager.py` property getter, documentation in `CLAUDE.md`.

## Error Handling

* All errors must use the OpenRouter-compatible format via `create_error(ErrorType, **context)`.
* Use `ErrorType` enum for all error classifications. Never hardcode status codes in route handlers.
* Provider errors must be extracted and wrapped, not passed through raw.
* Log errors with request context (request_id, provider, model).

## Testing

* Write tests before business logic when feasible (TDD Cycle above).
* Never modify existing tests to make failing code pass.
* Unit tests: `python -m pytest tests/unit/ -v` (158 tests, no external deps).
* Integration tests: `python -m pytest tests/api/ -v` (requires running service on :8777).
* All tests: `python -m pytest tests/ -v`.
* Docker: `docker compose up -d --build`. Always rebuild after code changes — the container copies source at build time.
* Server update: `docker compose up -d --build` rebuilds the image and restarts the container. Verify with `curl http://localhost:8777/health`.
* Unit tests cover: stream processing, provider logic, error handling, config loading, sanitization, utilities, services, middleware.

## Integration Protocol

Before implementing a feature that touches multiple systems:

1. Read `CLAUDE.md` — identify affected systems
2. Read module docstrings of affected files
3. `grep -r "ARCH:" src/` for architectural decisions in affected areas
4. `grep -r "INVARIANT:" src/` for constraints that must be preserved
5. Check `config/` YAML files if new config entries needed
6. Check `src/core/error_handling/error_types.py` if new error types needed; use `create_error(ErrorType, **context)` for all errors

## Auto-Lessons

When a task requires 3+ fix iterations on the same issue category, create a file in `lessons/` named `YYYY-MM-DD-short-slug.md`. Structure: What happened, Root cause, Actionable rule, Code example (wrong vs right). Integrate the rule into the relevant section of this document.
