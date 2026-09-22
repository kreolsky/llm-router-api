#!/usr/bin/env python3
"""Print one fresh router API key (nnp-v1-<64 hex>) to stdout.

Replaces the old GET /tools/generate_key endpoint: key minting is an
operator CLI action, not an HTTP surface. It NEVER edits config and is
NEVER imported by the app — paste the printed key into
config/user_keys.yaml (together with its restrictions) and reload.

Run (standalone CLI, from the repo root):

    python scripts/generate_key.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.generate_key import generate_key  # noqa: E402


def main() -> int:
    print(generate_key())
    return 0


if __name__ == "__main__":
    sys.exit(main())
