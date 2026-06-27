"""Unit tests for src/core/context.py — RequestContext dataclass."""

import pytest

from src.core.context import RequestContext


class TestRequestContext:

    def test_frozen_immutable(self):
        """RequestContext is frozen — cannot set attributes."""
        ctx = RequestContext(request_id="r1")
        with pytest.raises(Exception):
            ctx.request_id = "x"

    def test_with_project_name_returns_new_instance(self):
        """with_project_name returns a new instance, original unchanged."""
        ctx = RequestContext(request_id="r1")
        updated = ctx.with_project_name("proj-a")
        assert updated is not ctx
        assert updated.request_id == "r1"
        assert updated.project_name == "proj-a"
        # Original unchanged
        assert ctx.project_name is None

    def test_default_project_name_none(self):
        """project_name defaults to None."""
        ctx = RequestContext(request_id="r1")
        assert ctx.project_name is None
