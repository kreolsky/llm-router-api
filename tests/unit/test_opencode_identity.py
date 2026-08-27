"""Unit tests for src/core/opencode_identity.py — id format, registry, headers."""

import re

from src.core.opencode_identity import (
    SessionRegistry,
    new_session_id,
    opencode_session_headers,
)

SESSION_ID_RE = re.compile(r"^ses_[0-9A-Za-z]{26}$")


class TestNewSessionId:

    def test_matches_opencode_shape(self):
        assert SESSION_ID_RE.fullmatch(new_session_id())

    def test_ids_are_unique(self):
        ids = {new_session_id() for _ in range(100)}
        assert len(ids) == 100

    def test_time_part_encodes_timestamp_and_counter(self):
        """First 12 hex chars = low 48 bits of (ts << 12 | counter), starting at 1."""
        ts = 1_700_000_000_000
        first = new_session_id(timestamp_ms=ts)
        second = new_session_id(timestamp_ms=ts)
        expected_first = ((ts << 12) + 1) & 0xFFFFFFFFFFFF
        expected_second = ((ts << 12) + 2) & 0xFFFFFFFFFFFF
        assert first == f"ses_{expected_first:012x}" + first[16:]
        assert second == f"ses_{expected_second:012x}" + second[16:]
        # Random tails are 14 base62 chars each
        assert len(first) == 4 + 26

    def test_counter_resets_on_new_timestamp(self):
        ts_a, ts_b = 1_700_000_000_000, 1_700_000_000_001
        a1 = new_session_id(timestamp_ms=ts_a)
        a2 = new_session_id(timestamp_ms=ts_a)
        b1 = new_session_id(timestamp_ms=ts_b)
        assert int(a1[4:16], 16) + 1 == int(a2[4:16], 16)
        assert int(b1[4:16], 16) == ((ts_b << 12) + 1) & 0xFFFFFFFFFFFF


class TestSessionRegistry:

    def test_same_key_returns_stable_id(self):
        registry = SessionRegistry(ttl=60.0)
        assert registry.session_id("glm:proj", now=1.0) == registry.session_id("glm:proj", now=2.0)

    def test_different_keys_get_different_ids(self):
        registry = SessionRegistry(ttl=60.0)
        assert registry.session_id("glm:a", now=1.0) != registry.session_id("glm:b", now=1.0)

    def test_idle_key_expires_after_ttl(self):
        """TTL is idle-based: expiry counts from the last activity, not creation."""
        registry = SessionRegistry(ttl=10.0)
        early = registry.session_id("glm:proj", now=1.0)
        within = registry.session_id("glm:proj", now=10.5)  # 9.5s later: still alive, refreshes
        expired = registry.session_id("glm:proj", now=21.0)  # 10.5s after the last touch: past TTL
        assert early == within
        assert expired != early

    def test_expiry_is_lazy_no_background_task(self):
        registry = SessionRegistry(ttl=10.0)
        registry.session_id("a", now=1.0)
        registry.session_id("b", now=2.0)
        # Touching key 'a' at t=100 evicts expired 'b' as a side effect
        registry.session_id("a", now=100.0)
        assert "b" not in registry._sessions


class TestOpencodeSessionHeaders:

    def test_returns_both_header_names_with_same_value(self):
        headers = opencode_session_headers("glm:proj", ttl=3600.0)
        assert set(headers) == {"x-session-affinity", "X-Session-Id"}
        assert SESSION_ID_RE.fullmatch(headers["X-Session-Id"])
        assert headers["x-session-affinity"] == headers["X-Session-Id"]

    def test_same_key_stable_across_calls(self):
        first = opencode_session_headers("glm:proj", ttl=3600.0)
        second = opencode_session_headers("glm:proj", ttl=3600.0)
        assert first == second

    def test_ttl_change_rebuilds_registry(self):
        first = opencode_session_headers("glm:proj", ttl=3600.0)
        rebuilt = opencode_session_headers("glm:proj", ttl=60.0)
        assert first != rebuilt
