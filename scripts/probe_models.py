#!/usr/bin/env python3
"""Offline probe for model capabilities the upstream /models endpoint hides.

For providers whose /models returns nothing useful (deepseek, kimi/moonshot),
this script discovers capabilities empirically by sending REAL (PAID) chat
completion requests through the router and parsing the responses/errors:

  * vision      — one request with a 1x1 PNG in image_url (200 -> supported,
                  "image"/"vision"/"unsupported" error -> not supported)
  * context     — one overlong prompt; parse the "maximum context length is N"
                  error for the window size
  * max output  — one request with a huge max_tokens; parse the cap

It NEVER edits config and is NEVER imported by the app. It prints a YAML draft
to stdout for manual review / pasting into config/model_info.yaml.

Run (standalone CLI; needs a router API key with access to the target models):

    python scripts/probe_models.py deepseek/flash kimi \\
        --base-url http://localhost:8777 \\
        --api-key nnp-v1-...

    # restrict to specific probes:
    python scripts/probe_models.py deepseek/flash --only vision --only context

Each probe is a separate paid request; a model with all three probes costs ~3
chat calls (tiny outputs). Review the printed YAML before committing it.
"""
import argparse
import base64
import os
import re
import sys
from typing import Optional

import httpx
import yaml

# Minimal 1x1 transparent PNG (vision probe payload).
_PNG_1x1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# Heuristics for parsing upstream error messages (best-effort, provider-specific).
_CTX_PATTERNS = [
    re.compile(r"maximum context length is (\d[\d,]*)", re.I),
    re.compile(r"context (?:length|window).*?(\d[\d,]*)\s*tokens?", re.I),
    re.compile(r"(\d[\d,]*)\s*tokens.*?context", re.I),
    re.compile(r"reduce.*?by.*?(\d[\d,]*)", re.I),
]
_MAX_OUTPUT_PATTERNS = [
    re.compile(r"max_tokens?.*?(?:maximum|exceeds|at most).*?(\d[\d,]*)", re.I),
    re.compile(r"maximum.*?(\d[\d,]*)\s*(?:completion|output)?\s*tokens?", re.I),
]
_NO_VISION_HINTS = ("image", "vision", "multimodal", "multi-modal", "unsupported", "does not support", "not support")


def _clean_int(raw: str) -> int:
    return int(raw.replace(",", ""))


def _post(client: httpx.Client, base_url: str, api_key: str, body: dict, timeout: float = 60.0) -> tuple[int, dict]:
    """POST to /v1/chat/completions; return (status_code, parsed_json_or_error_dict)."""
    resp = client.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"error": {"message": resp.text}}


def _error_text(data: dict) -> str:
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message", "")) + " " + str(err.get("metadata", {}).get("raw", ""))
    return str(data)


def probe_vision(client, base_url, api_key, model_id) -> Optional[bool]:
    """True = vision accepted, False = explicitly unsupported, None = unknown."""
    body = {
        "model": model_id,
        "max_tokens": 1,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "1"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_1x1_B64}"}},
            ],
        }],
    }
    status, data = _post(client, base_url, api_key, body)
    if status == 200:
        return True
    text = _error_text(data).lower()
    if any(h in text for h in _NO_VISION_HINTS):
        return False
    return None


def probe_context_length(client, base_url, api_key, model_id, target_tokens: int = 350000) -> Optional[int]:
    """Send an overlong prompt; parse the context-window cap from the error."""
    # ~2 tokens per "hello " repeat; overshoot any plausible window.
    repeats = max(1, target_tokens // 2)
    filler = "hello " * repeats
    body = {
        "model": model_id,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": filler}],
    }
    status, data = _post(client, base_url, api_key, body, timeout=120.0)
    if status == 200:
        return None  # didn't overflow -> unknown (window >= target)
    text = _error_text(data)
    for pat in _CTX_PATTERNS:
        m = pat.search(text)
        if m:
            return _clean_int(m.group(1))
    return None


def probe_max_output(client, base_url, api_key, model_id) -> Optional[int]:
    """Request a huge max_tokens; parse the output cap from the error."""
    body = {
        "model": model_id,
        "max_tokens": 1_000_000,
        "messages": [{"role": "user", "content": "1"}],
    }
    status, data = _post(client, base_url, api_key, body, timeout=60.0)
    if status == 200:
        return None  # silently clamped -> unknown
    text = _error_text(data)
    for pat in _MAX_OUTPUT_PATTERNS:
        m = pat.search(text)
        if m:
            return _clean_int(m.group(1))
    return None


def probe_model(client, base_url, api_key, model_id, probes: set) -> dict:
    """Run the requested probes for one model; return a result dict."""
    print(f"[{model_id}] probing {sorted(probes)} ...", file=sys.stderr)
    result: dict = {}
    if "vision" in probes:
        result["supports_vision"] = probe_vision(client, base_url, api_key, model_id)
    if "context" in probes:
        result["context_length"] = probe_context_length(client, base_url, api_key, model_id)
    if "max-tokens" in probes:
        result["max_completion_tokens"] = probe_max_output(client, base_url, api_key, model_id)
    print(f"[{model_id}] -> {result}", file=sys.stderr)
    return result


def to_yaml_draft(model_id: str, res: dict) -> Optional[dict]:
    """Convert probe results into a model_info.yaml entry (None if nothing found)."""
    entry: dict = {}
    vision = res.get("supports_vision")
    if vision is True:
        entry.setdefault("architecture", {})["input_modalities"] = ["text", "image"]
        entry["architecture"]["output_modalities"] = ["text"]
    elif vision is False:
        entry.setdefault("architecture", {})["input_modalities"] = ["text"]
        entry["architecture"]["output_modalities"] = ["text"]
    if res.get("context_length"):
        entry["context_length"] = res["context_length"]
    if res.get("max_completion_tokens"):
        entry["max_completion_tokens"] = res["max_completion_tokens"]
    if not entry:
        return None
    entry = {model_id: entry}
    # keep a stable, readable key order
    return entry


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("models", nargs="+", help="model_id(s) to probe (as in models.yaml)")
    ap.add_argument("--base-url", default=os.getenv("PROBE_BASE_URL", "http://localhost:8777"))
    ap.add_argument("--api-key", default=os.getenv("PROBE_API_KEY"),
                    help="router API key (or set PROBE_API_KEY env)")
    ap.add_argument("--only", action="append", choices=["vision", "context", "max-tokens"],
                    help="restrict probes (repeatable); default: all three")
    ap.add_argument("--tokens", type=int, default=350000,
                    help="filler token target for the context probe (default 350000)")
    args = ap.parse_args()

    if not args.api_key:
        print("error: --api-key (or PROBE_API_KEY env) is required", file=sys.stderr)
        return 2

    probes = set(args.only) if args.only else {"vision", "context", "max-tokens"}

    print("WARNING: this makes real paid chat requests (1 per probe per model).",
          file=sys.stderr)

    drafts = []
    with httpx.Client() as client:
        for model_id in args.models:
            res = probe_model(client, args.base_url, args.api_key, model_id, probes)
            draft = to_yaml_draft(model_id, res)
            if draft:
                drafts.append(draft)
            else:
                print(f"[{model_id}] nothing detected; skipped (fill in manually).",
                      file=sys.stderr)

    print("\n# --- probe draft: review and paste the relevant entries into "
          "config/model_info.yaml ---", file=sys.stderr)
    print("model_info:")
    for d in drafts:
        dumped = yaml.safe_dump(d, sort_keys=False, allow_unicode=True, width=1000)
        for line in dumped.rstrip().splitlines():
            print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
