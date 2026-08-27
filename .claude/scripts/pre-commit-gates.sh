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

# ADVISORY, never blocking: the tree carries ~526 pre-existing ruff findings under
# default rules and no ruff config. Making that a gate on day one would mean a red
# block nobody can clear, which is how a gate becomes something people route around.
# Promote it once the backlog is cleaned or a baseline is committed.
if command -v ruff >/dev/null 2>&1; then
  N=$(ruff check src tests 2>/dev/null | grep -cE '^(src|tests)/' || true)
  [ "${N:-0}" -gt 0 ] && printf '  note  ruff: %s finding(s) — advisory, not gated (see this script)\n' "$N"
fi

if [ ${#FAILED[@]} -gt 0 ]; then
  printf '\nBLOCKED — %d gate(s) failed: %s\n' "${#FAILED[@]}" "${FAILED[*]}"
  exit 1
fi
echo "All gates green."
