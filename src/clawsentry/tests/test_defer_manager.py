"""Tests for DEFER timeout manager."""

from __future__ import annotations

import asyncio

import pytest

from clawsentry.gateway.defer_manager import DeferManager


class TestDeferManager:

    def test_default_timeout_action_is_block(self):
        dm = DeferManager()
        assert dm.timeout_action == "block"

    def test_custom_timeout_action(self):
        dm = DeferManager(timeout_action="allow", timeout_s=60.0)
        assert dm.timeout_action == "allow"
        assert dm.timeout_s == 60.0

    @pytest.mark.asyncio
    async def test_register_and_resolve_defer(self):
        dm = DeferManager()
        dm.register_defer("req-1")
        assert dm.is_pending("req-1")
        dm.resolve_defer("req-1", "allow", "operator approved")
        assert not dm.is_pending("req-1")

    @pytest.mark.asyncio
    async def test_wait_for_resolution_returns_decision(self):
        dm = DeferManager(timeout_s=5.0)
        dm.register_defer("req-2")

        async def resolve_later():
            await asyncio.sleep(0.05)
            dm.resolve_defer("req-2", "allow", "approved")

        asyncio.create_task(resolve_later())
        decision, reason = await dm.wait_for_resolution("req-2")
        assert decision == "allow"
        assert reason == "approved"

    @pytest.mark.asyncio
    async def test_timeout_returns_block(self):
        dm = DeferManager(timeout_action="block", timeout_s=0.1)
        dm.register_defer("req-3")
        decision, reason = await dm.wait_for_resolution("req-3")
        assert decision == "block"
        assert "timeout" in reason.lower()

    @pytest.mark.asyncio
    async def test_timeout_returns_allow(self):
        dm = DeferManager(timeout_action="allow", timeout_s=0.1)
        dm.register_defer("req-4")
        decision, reason = await dm.wait_for_resolution("req-4")
        assert decision == "allow"
        assert "timeout" in reason.lower()

    def test_pending_count(self):
        dm = DeferManager()
        dm.register_defer("a")
        dm.register_defer("b")
        assert dm.pending_count == 2
        dm.resolve_defer("a", "allow", "ok")
        assert dm.pending_count == 1

    def test_resolve_nonexistent_does_not_raise(self):
        dm = DeferManager()
        dm.resolve_defer("nonexistent", "allow", "ok")  # should not raise

    @pytest.mark.asyncio
    async def test_wait_nonexistent_returns_timeout_action(self):
        dm = DeferManager(timeout_action="block")
        decision, reason = await dm.wait_for_resolution("missing")
        assert decision == "block"
        assert "not found" in reason
