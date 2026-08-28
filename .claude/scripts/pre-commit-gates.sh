#!/usr/bin/env bash
# Local mirror of every CHEAP structural gate — the ones needing no network, no Docker
# and no running service. The whole block runs in a couple of seconds, so there is no
# reason to discover these failures after a push.
#
# NOT covered here on purpose (that is what `/run-tests` and a live drive are for):
# pytest, the Docker build, any request against :8777.
#
# NOT here either: plan-shape. A plan is written in one session and executed in another,
# and it is normally still uncommitted when the implementation commit lands — gating the
# commit would block FINISHED work over a draft whose job is already done. Its enforcement
# points are the two moments where a reshape is still free: the Write|Edit hook
# (settings.json) and /implement's plan load.
#
# Usage: .claude/scripts/pre-commit-gates.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

FAILED=()

run_gate() {
  local name="$1"; shift
  if "$@" >/tmp/gate-out.txt 2>&1; then
    printf '  ok    %s\n' "$name"
  else
    printf '  FAIL  %s\n' "$name"
    sed 's/^/        /' /tmp/gate-out.txt
    FAILED+=("$name")
  fi
}

echo "━━━ pre-commit gates ━━━"
run_gate "invariant-why"  python3 .claude/scripts/invariant-why-gate.py
run_gate "systems-index"  python3 .claude/scripts/systems-index.py --check
run_gate "func-length"    python3 .claude/scripts/func-length-gate.py
run_gate "debt-ledger"    python3 .claude/scripts/debt-gate.py
run_gate "cyrillic-src"   python3 .claude/scripts/cyrillic-src-gate.py

# ruff: BLOCKING over src/ and tests/. The rule set is pinned in pyproject.toml
# and the binary in requirements-dev.txt (ruff==0.16.0) — a gate whose rules
# depend on who runs it is not a gate. tests/ carries per-file-ignores for the
# patterns that are correct in a test (mocked async sleeps, positional unpacks,
# assert-raises in drivers — see pyproject.toml); everything else is enforced.
run_gate "ruff"           ruff check src/ tests/

if [ ${#FAILED[@]} -gt 0 ]; then
  printf '\nBLOCKED — %d gate(s) failed: %s\n' "${#FAILED[@]}" "${FAILED[*]}"
  exit 1
fi
echo "All gates green."
