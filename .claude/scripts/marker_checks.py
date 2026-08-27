#!/usr/bin/env python3
"""Shared marker-adjacency checks and the source-file walk used by every local gate.

The `INVARIANT:` contract (documentation.md): every marker is followed by a `Why:` on the
same line or within the next 2 lines — the Why is what survives refactors. Regexes
tolerate the optional severity tag form `INVARIANT(data-loss):`.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

INVARIANT_RE = re.compile(r"\bINVARIANT(\([a-z-]+\))?:")
WHY_RE = re.compile(r"\bWhy:")
ADJACENCY_WINDOW = 2  # Why: on the marker line or within the next 2 lines

# Marker-class prefixes for density measurement (marker-density.py). Each matches the
# ALL-CAPS marker token at a word boundary followed by `:` — the same shape as
# INVARIANT_RE. WHY_MARKER_RE is the standalone `WHY:` marker (documentation.md: a LOCAL
# non-obvious choice); it is distinct from WHY_RE, the `Why:` word that satisfies an
# INVARIANT's adjacency contract. ARCH_RE also matches the ad-hoc tagged form
# `ARCH (tag):` (unsanctioned — documentation.md permits tags only on INVARIANT — but
# still ARCH signal, so density counts it; ~107 exist in the tree).
ARCH_RE = re.compile(r"\bARCH(?:\s*\([^)]*\))?:")
SYSTEM_RE = re.compile(r"\bSYSTEM(?:\s*\([^)]*\))?:")
WHY_MARKER_RE = re.compile(r"\bWHY(?:\s*\([^)]*\))?:")
DEBT_RE = re.compile(r"\bDEBT(?:\s*\([^)]*\))?:")
CLASS_RES: list[tuple[str, re.Pattern]] = [
    ("ARCH", ARCH_RE),
    ("INVARIANT", INVARIANT_RE),
    ("SYSTEM", SYSTEM_RE),
    ("WHY", WHY_MARKER_RE),
    ("DEBT", DEBT_RE),
]


# Vendored / generated / VCS trees no gate ever scans. Single source: the sets used to
# drift per script (one skipped `.git`, another did not).
SKIP_DIRS = frozenset({"__pycache__", "node_modules", "dist", ".venv", ".git"})


def iter_files(
    base: Path,
    suffixes: tuple[str, ...] | None = None,
    extra_skip: frozenset[str] | set[str] = frozenset(),
) -> Iterator[Path]:
    """Yield files under `base`, sorted, pruning SKIP_DIRS + `extra_skip` subtrees.

    INVARIANT: excluded directories are pruned from the walk, never filtered out of its
    results.  Why: `rglob` descends into node_modules regardless of any later `if part in
    SKIP` test — a 418MB tree turned this scan into 40s of pure I/O for 615 files, which
    is what made the "~1.5s" pre-commit block take two minutes.
    """
    if not base.exists():
        return
    skip = SKIP_DIRS | frozenset(extra_skip)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in skip]
        here = Path(dirpath)
        for name in filenames:
            if suffixes is None or name.endswith(suffixes):
                found.append(here / name)
    yield from sorted(found)


def invariants_missing_why(lines: list[str]) -> list[int]:
    """0-based indices of INVARIANT lines with no Why: within the adjacency window."""
    missing = []
    for i, line in enumerate(lines):
        if not INVARIANT_RE.search(line):
            continue
        window = lines[i : i + ADJACENCY_WINDOW + 1]
        if not any(WHY_RE.search(w) for w in window):
            missing.append(i)
    return missing
