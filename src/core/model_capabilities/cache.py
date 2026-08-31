"""CapabilitiesCache: the auto-cache layer's in-memory store + persistence."""

import contextlib
import json
import os
import tempfile
import time
from typing import Any

from ..logging import logger


class CapabilitiesCache:
    """In-memory cache of upstream model capabilities, persisted to disk.

    Stores ``{model_id: {"data": <stored form>, "fetched_at": float, "source": str}}``.
    Read from disk on startup so data is available even when upstreams are down.
    On refresh failure, existing entries are retained (stale-if-error).
    """

    def __init__(self, path: str = "data/model_cache.json"):
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}

    def load(self) -> None:
        """Read the cache from disk; ignore missing or corrupt files."""
        try:
            with open(self._path) as f:
                raw = json.load(f)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                f"Model cache file {self._path} is corrupt, ignoring cached capabilities",
                extra={"config": {"model_cache_path": self._path}},
            )
            return
        if not isinstance(raw, dict):
            return
        cleaned: dict[str, dict[str, Any]] = {}
        for model_id, entry in raw.items():
            if isinstance(entry, dict) and isinstance(entry.get("data"), dict):
                cleaned[model_id] = entry
        self._data = cleaned
        logger.info(
            f"Loaded {len(cleaned)} cached model capabilities from {self._path}",
            extra={"config": {"model_cache_entries": len(cleaned)}},
        )

    def get(self, model_id: str) -> dict[str, Any] | None:
        """Return the STORED-form data for a model, or None if absent."""
        entry = self._data.get(model_id)
        return None if entry is None else entry.get("data")

    def get_meta(self, model_id: str) -> dict[str, Any] | None:
        """Return provenance (source, fetched_at) for a model, or None."""
        entry = self._data.get(model_id)
        if entry is None:
            return None
        return {"source": entry.get("source"), "fetched_at": entry.get("fetched_at")}

    def upsert(self, model_id: str, data: dict[str, Any], source: str) -> None:
        """Insert/replace a model's stored capabilities with a fresh timestamp."""
        self._data[model_id] = {
            "data": data or {},
            "fetched_at": time.time(),
            "source": source,
        }

    def persist(self) -> None:
        """Atomically write the cache to disk.

        Uses a UNIQUE temp file per write (mkstemp) plus os.replace, so a crash
        between write and rename never leaves a truncated cache. Uniqueness also
        keeps concurrent writers (a stray second process against the same data/
        volume) from renaming each other's source file (ENOENT on os.replace);
        last writer wins on the final path. Within the one-worker invariant
        (see Dockerfile) there is exactly one writer.
        """
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".model_cache.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f)
            os.replace(tmp, self._path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
