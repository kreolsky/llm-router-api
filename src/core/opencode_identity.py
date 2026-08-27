"""Synthetic OpenCode session identity: ses_* id generator and session registry.

Faithful port of sst/opencode packages/schema/src/identifier.ts create():
12 hex chars encoding the low 48 bits of (timestamp_ms << 12 | per-ms counter),
plus 14 chars drawn as byte % 62 from the 62-char alphabet (the source's
slight modulo bias is preserved on purpose). The 'ses_' type prefix comes from
packages/core/src/id/id.ts.

Session ids must be STABLE for the lifetime of a client session:
x-session-affinity exists for sticky routing, so a fresh random id per request
is a detectable anomaly. SessionRegistry maps one stable key (provider name +
project_name from RequestContext) to one ses_* id, refreshed on activity and
lazily evicted after a TTL (OPENCODE_SESSION_TTL, no background task).
"""
# SYSTEM: opencode-identity — synthetic ses_* ids and the session registry
import os
import time

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_SESSION_PREFIX = "ses_"
_TOTAL_LENGTH = 26
_TIME_BYTES = 6  # 12 hex chars
_COUNTER_BITS = 12

_last_timestamp_ms = 0
_counter = 0


def _create_identifier(timestamp_ms: int) -> str:
    """Body of an OpenCode identifier: 12 hex time chars + 14 random base62 chars."""
    global _last_timestamp_ms, _counter
    if timestamp_ms != _last_timestamp_ms:
        _last_timestamp_ms = timestamp_ms
        _counter = 0
    _counter += 1
    value = (timestamp_ms << _COUNTER_BITS) + _counter
    time_part = "".join(
        f"{(value >> (8 * (_TIME_BYTES - 1 - i))) & 0xFF:02x}" for i in range(_TIME_BYTES)
    )
    rand_part = "".join(_ALPHABET[b % 62] for b in os.urandom(_TOTAL_LENGTH - 2 * _TIME_BYTES))
    return time_part + rand_part


def new_session_id(timestamp_ms: int | None = None) -> str:
    """Generate a full OpenCode session id: 'ses_' + 26 chars.

    timestamp_ms is injectable for deterministic tests only.
    """
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    return _SESSION_PREFIX + _create_identifier(ts)


class SessionRegistry:
    """Maps stable client keys to synthetic session ids with an activity TTL.

    One key = one ses_* id for as long as requests keep arriving within the
    TTL; an idle key is lazily evicted on the next insert and gets a fresh id
    when it returns.
    """

    def __init__(self, ttl: float = 3600.0):
        self.ttl = ttl
        self._sessions: dict[str, tuple[str, float]] = {}

    def session_id(self, key: str, now: float | None = None) -> str:
        """Return the stable session id for key, refreshing its last-seen time."""
        now = time.monotonic() if now is None else now
        entry = self._sessions.get(key)
        if entry is not None and now - entry[1] < self.ttl:
            self._sessions[key] = (entry[0], now)
            return entry[0]
        self._sessions = {
            k: v for k, v in self._sessions.items() if now - v[1] < self.ttl
        }
        session_id = new_session_id()
        self._sessions[key] = (session_id, now)
        return session_id


_registry: SessionRegistry | None = None


def opencode_session_headers(key: str, ttl: float = 3600.0) -> dict[str, str]:
    """Per-request OpenCode session headers for a registry key.

    Module-level singleton so provider-cache rebuilds on config reload do not
    reset live sessions; a TTL change rebuilds it (rare, operator-initiated).
    """
    global _registry
    if _registry is None or _registry.ttl != ttl:
        _registry = SessionRegistry(ttl)
    session_id = _registry.session_id(key)
    return {"x-session-affinity": session_id, "X-Session-Id": session_id}
