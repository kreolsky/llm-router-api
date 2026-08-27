#!/usr/bin/env python3
"""PostToolUse(ExitPlanMode) hook: persist the approved plan to plans/
and append a draft complexity estimate (size-estimate.py --plan).

The plan text arrives in the tool input. Hooks receive it as JSON on stdin
(Claude Code PostToolUse contract); we fall back to $CLAUDE_TOOL_INPUT. The
estimate is advisory — deterministic, informational, and nothing downstream
blocks on it.

Emits a JSON {"systemMessage": ...} so the path + estimate surface in context.
Silent on any failure path EXCEPT it still tells the assistant — never swallow.
"""
import sys, os, json, re, time, subprocess, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]   # repo root (.claude/scripts -> root)
PLANS = ROOT / "plans"
SIZER = ROOT / ".claude" / "scripts" / "size-estimate.py"
SHAPER = ROOT / ".claude" / "scripts" / "plan-shape-gate.py"
SLUGS = ["amber", "brave", "calm", "swift", "quiet", "bright", "lunar", "nimble"]

def emit(msg):
    print(json.dumps({"systemMessage": msg})); sys.exit(0)

def read_input():
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw:
        raw = os.environ.get("CLAUDE_TOOL_INPUT", "")
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw  # already the plan string
    # PostToolUse payload nests the tool input; tolerate a few shapes.
    for key in ("tool_input", "toolInput", "input"):
        if isinstance(data.get(key), dict) and "plan" in data[key]:
            return data[key]["plan"]
    return data.get("plan", "")

def slug(text):
    m = re.search(r"^#+\s*(.+)$", text, re.M)
    base = m.group(1) if m else SLUGS[int(time.time()) % len(SLUGS)]
    s = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")[:48]
    return s or "plan"

def archive_old(keep_days=90):
    """Sweep plans older than keep_days into plans/archive/YYYY-MM/.

    Runs on every plan approval so the directory never needs a ritual to stay
    navigable. Advisory: any failure is swallowed — it must never cost a save.
    archive/ itself is always skipped.
    """
    cutoff = time.time() - keep_days * 86400
    moved = 0
    for p in PLANS.glob("*.md"):
        if p.stat().st_mtime > cutoff:
            continue
        dest = PLANS / "archive" / time.strftime("%Y-%m", time.localtime(p.stat().st_mtime))
        try:
            dest.mkdir(parents=True, exist_ok=True)
            p.rename(dest / p.name)
            moved += 1
        except OSError:
            pass
    return moved


def main():
    plan = read_input().strip()
    if not plan:
        emit("⚠ save-plan hook: no plan text in tool input — plan NOT saved. Save it to plans/ manually.")
    PLANS.mkdir(parents=True, exist_ok=True)
    fname = f"{int(time.time() * 1000)}-{slug(plan)}.md"
    path = PLANS / fname
    path.write_text(plan + "\n", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(SIZER), "--plan", str(path), "--append"],
        capture_output=True, text=True,
    ).stdout.strip()
    rel = path.relative_to(ROOT)
    # Shape check at WRITE time, not only at commit time: a plan is read and acted on
    # long before it is committed, so a violation surfaced at the commit has already
    # done its damage. The gate blocks the commit; here it only tells.
    shape = subprocess.run(
        [sys.executable, str(SHAPER), str(path)], capture_output=True, text=True
    )
    shape_tail = "" if shape.returncode == 0 else (
        "\n\n⚠ OFF-SHAPE — pre-commit gate `plan-shape` will block this:\n"
        + shape.stdout.strip()
        + "\nRewrite the plan to the five allowed sections, do not append to it."
    )
    swept = archive_old()
    tail = f"\n({swept} plan(s) older than 90d swept into plans/archive/)" if swept else ""
    emit(f"Plan saved → {rel}\n{out}{tail}{shape_tail}")

if __name__ == "__main__":
    main()
