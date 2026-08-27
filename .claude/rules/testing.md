# Testing

* Write tests before business logic when feasible (the TDD cycle is in `workflow.md`).
* Never modify an existing test to make failing code pass.
* Commands, Docker rebuild semantics, speed and isolation → `.claude/rules-scoped/testing-ops.md`.
  Read it before running or debugging a suite.

## After a run: propose, don't ask

A run that ends in a list of observations is half a turn. Close it with a SHORT plan — what
gets fixed, in what order — and start it without waiting for permission.

* **A bug found by a run is fixed, always**, unless the fix would change product behaviour
  (a response shape, an access rule, a stored row, a contract a client reads). Those are the
  only ones that stop and ask, and they stop with a recommendation, not with a question.
* **Say what was NOT proven.** A green run whose falsification you skipped, a provider you
  did not drive, a streaming path that passed both with and without the fix — name it in the
  same breath as the green.

## Reports are user scenarios, not a changelog of the code

State what a client of this router can now do, or can no longer be harmed by. The code path
is supporting detail — it goes after the scenario, or in the diff.

* **Wrong**: "`_merge_request_headers` now dedupes, the passthrough list is re-cased, the
  registry TTL moved." Three identifiers, zero consequences.
* **Right**: "A Kilo Code session now keeps one stable `ses_*` id across a whole project, so
  the upstream no longer sees every request as a new session. A config reload during a live
  stream no longer cuts the stream off mid-answer."
* This holds for review findings, drive reports and commit bodies alike.

## A green test is not evidence — bind the contract, not your own assumption

A test written from the implementation, by its author, asserts what the code already does.

* **Assert over the DERIVED source, not a literal.** Walk the real list (`app.routes`, the
  `ErrorType` enum, the configured providers) so the assertion binds two components and
  covers the next member. A literal in the test mirroring a literal in the code drifts WITH it.
* **A test with no failing branch is not a test.** `if <expected>: assert … else: assert
  <also fine>` passes on every outcome.
* **Test the principal that must be REFUSED.** An access guard exercised only by the key that
  passes it is untested — a model-access check needs the key that must be denied.
* **Verify with a different tool than you built with.** `curl`-ing your own path proves the
  path you wrote, not the one a real client derives.
* **A test that must change when the implementation changes is testing PAST the interface.**
  The interface is everything a caller must know — signature plus invariants, ordering, error
  modes, required config. Every hidden seam (`patch("mod.symbol")`, `monkeypatch.setattr`,
  `obj._x`) is the module's internal seam exposed because a test reached for it. A growing
  count of such targets in one module is the signal to reshape the module, not to grep harder.
* **An exact-surface assertion obliges you to pin every flag that shapes it.** Equality over
  a served surface (the `/v1/models` payload, the error envelope) implicitly asserts each
  `if <FLAG>:` branch — so the test passes or fails on the runner's `.env`, not on the code,
  and the failure misreads as drift. Pin every axis in ONE fixture carrying an `INVARIANT:`
  that names the obligation; never loosen the assertion to a subset — that is what deletes
  its value. Adding a gated branch ⇒ grep for tests asserting that surface's totality.
* **Pin every flag on the path from the test's entry to the patched symbol** — not only the
  one visible in the assertion. An early `return` on unset config makes the mock UNREACHABLE,
  so the test measures the runner's `.env` instead of the code.
