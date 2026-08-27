#!/usr/bin/env python3
"""Generated index of `SYSTEM:` subsystems — never hand-maintained (see documentation.md:
code is the single source of truth). Greps source for `SYSTEM: <name> — <desc>` markers.

Usage:
  systems-index.py                 # print the index (name → file:line — desc), sorted
  systems-index.py <noun>          # filter to names/descs matching <noun> (discovery gate)
  systems-index.py --check         # GATE: exit 1 on drift (marker count over allowlist cap)
                                   # or on a stale committed SYSTEMS.md (line numbers excluded —
                                   # see _strip_line_numbers: they drift on any edit above a marker
                                   # and carry no staleness signal for discovery)
  systems-index.py --write         # regenerate SYSTEMS.md at repo root

`--check` is a GATE (CI: structure-gates step). Default cap is 2 markers per name (one
frontend + one backend entry for a cross-stack system); legit multi-module packages get a
higher cap in `.claude/baselines/systems-allowlist.json` ({name: max_count}). The contract
(see documentation.md): `SYSTEM:` on entry files only, never on incidental lines or
cross-references — those are prose `see SYSTEM: <name>`.

`--write` renders `SYSTEMS.md` (committed, GENERATED header) merging optional aliases from
`.claude/systems-aliases.json` ({name: [synonyms, incl. Russian task nouns]}) so discovery
greps can start from the catalog instead of guessing nouns.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
ROOTS = ["src"]
ALLOWLIST = ROOT / ".claude" / "baselines" / "systems-allowlist.json"
ALIASES = ROOT / ".claude" / "systems-aliases.json"
CATALOG = ROOT / "SYSTEMS.md"
DEFAULT_CAP = 1  # one entry file per subsystem (single-stack Python service)
# `# SYSTEM: name — desc`; desc (after — / – / -) optional.
# Name may be multi-word ("markdown content normalize"); non-greedy up to the separator.
MARKER = re.compile(r"SYSTEM:\s*([a-z0-9][a-z0-9 _-]*?)\s*(?:[—–-]{1,2}\s+(.*))?$")


def collect() -> dict[str, list[tuple[str, str]]]:
    """normalized-name → [(file:line, desc), ...]; spaces in names normalized to '-'."""
    out = subprocess.run(
        ["grep", "-rn", "--include=*.py", "SYSTEM:", *ROOTS],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout
    by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for line in out.splitlines():
        try:
            path, lineno, body = line.split(":", 2)
        except ValueError:
            continue
        if "test" in path or "spec" in path:  # incidental mentions in tests are not entries
            continue
        if re.search(r"\bsee SYSTEM:", body, re.IGNORECASE):  # prose cross-reference, not an entry
            continue
        m = MARKER.search(body)
        if not m:
            continue
        name = re.sub(r"[\s_]+", "-", m.group(1).strip())
        desc = (m.group(2) or "").strip()
        by_name[name].append((f"{path}:{lineno}", desc))
    return by_name


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_line_numbers(text: str) -> str:
    """Drop `:line` suffixes from `path:line` refs for the freshness comparison.

    Line numbers shift on any insert/delete above a `SYSTEM:` marker, so they
    carry no staleness signal for the catalog's discovery purpose (name -> file).
    Excluding them stops CI from failing on pure line drift (a recurring class:
    a code change in `documents.py` moves the `transclusion` marker down N lines
    without touching it). The gate then fires only on real structural change:
    a new/removed/renamed system, or a changed desc/file/alias. The rendered
    SYSTEMS.md still keeps line numbers for navigation.
    """
    return re.sub(r":\d+(?=`)", "", text)


def render_catalog(by_name: dict[str, list[tuple[str, str]]]) -> str:
    """SYSTEMS.md body — one row per system: name · desc · entry file(s) · aliases."""
    aliases = load_json(ALIASES)
    lines = [
        "# SYSTEMS — subsystem catalog",
        "",
        "GENERATED — do not edit; run `.claude/scripts/systems-index.py --write`.",
        "",
        "Discovery: find your system (or an alias) here, then `grep -rn \"SYSTEM: <name>\"`",
        "and read the entry file(s). Aliases are hand-maintained in",
        "`.claude/systems-aliases.json`.",
        "",
        "| System | Description | Entry file(s) | Aliases |",
        "|--------|-------------|---------------|---------|",
    ]
    for name in sorted(by_name):
        # Sort BEFORE picking the desc — grep traversal order differs across hosts,
        # and a nondeterministic desc would flip the freshness check on CI.
        locs = sorted(by_name[name])
        desc = next((d for _, d in locs if d), "")
        files = "<br>".join(f"`{loc}`" for loc, _ in locs)
        alias = ", ".join(aliases.get(name, []))
        lines.append(f"| {name} | {desc} | {files} | {alias} |")
    lines.append("")
    return "\n".join(lines)


def check(by_name: dict[str, list[tuple[str, str]]]) -> int:
    caps = load_json(ALLOWLIST)
    over = {n: locs for n, locs in by_name.items()
            if len(locs) > caps.get(n, DEFAULT_CAP)}
    print(f"{len(by_name)} subsystems indexed.")
    rc = 0
    if over:
        rc = 1
        print(f"\n{len(over)} name(s) over cap — rewrite incidental markers to prose "
              f"`see SYSTEM: <name>`, or raise the cap in "
              f"{ALLOWLIST.relative_to(ROOT)} with justification:\n")
        for name in sorted(over, key=lambda n: -len(by_name[n])):
            cap = caps.get(name, DEFAULT_CAP)
            print(f"  {name} ({len(over[name])} > cap {cap}):")
            for loc, _ in over[name]:
                print(f"    {loc}")
    else:
        print("No drift (all names within allowlist caps).")
    # Freshness: committed SYSTEMS.md must match a fresh render. Line numbers
    # excluded (see _strip_line_numbers) so pure drift above a marker doesn't
    # fail CI — only a real catalog change (name/desc/file/alias) does.
    fresh = render_catalog(by_name)
    committed = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else ""
    if _strip_line_numbers(fresh) != _strip_line_numbers(committed):
        rc = 1
        print("\nSYSTEMS.md is STALE — regenerate and commit:\n"
              "  python3 .claude/scripts/systems-index.py --write")
    else:
        print("SYSTEMS.md is fresh.")
    return rc


def main(argv: list[str]) -> int:
    by_name = collect()

    if "--check" in argv:
        return check(by_name)

    if "--write" in argv:
        CATALOG.write_text(render_catalog(by_name), encoding="utf-8")
        print(f"SYSTEMS.md written ({len(by_name)} subsystems).")
        return 0

    needle = next((a for a in argv[1:] if not a.startswith("--")), None)
    aliases = load_json(ALIASES)
    for name in sorted(by_name):
        loc, desc = by_name[name][0]
        row = f"{name:32} {loc}  — {desc}"
        haystack = row + " " + " ".join(aliases.get(name, []))
        if needle is None or needle.lower() in haystack.lower():
            print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
