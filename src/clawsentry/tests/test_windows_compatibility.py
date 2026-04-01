"""Tests for Windows platform compatibility."""

import sys
from unittest.mock import patch
import pytest

from ..adapters.a3s_adapter import A3SCodeAdapter
from ..gateway.models import CanonicalEvent, EventType, DecisionTier, DecisionVerdict
from ..gateway.server import start_uds_server


class TestWindowsUDSHandling:
    """Test that UDS operations gracefully handle Windows platform."""

    @pytest.mark.asyncio
    async def test_start_uds_server_returns_none_on_windows(self):
        """UDS server should return None on Windows without crashing."""
        with patch("sys.platform", "win32"):
            from ..gateway.server import start_uds_server

            # Mock gateway object
            class MockGateway:
                pass

            gateway = MockGateway()
            result = await start_uds_server(gateway, "/tmp/test.sock")
            assert result is None

    @pytest.mark.asyncio
    async def test_adapter_fallback_on_windows(self):
        """Adapter should fall back to local decision on Windows."""
        with patch("sys.platform", "win32"):
            adapter = A3SCodeAdapter()

            event = CanonicalEvent(
                event_id="test-event",
                trace_id="test-trace",
                event_type=EventType.PRE_ACTION,
                session_id="test-session",
                agent_id="test-agent",
                source_framework="a3s-code",
                occurred_at="2026-04-01T00:00:00Z",
                payload={"tool": "bash", "command": "echo hello"},
                event_subtype="pre_tool_use",
                tool_name="bash",
                risk_hints=["shell_execution"],
            )

            # Should not crash, should return fallback decision
            decision = await adapter.request_decision(event, deadline_ms=1000)
            assert decision is not None
            assert decision.decision in [DecisionVerdict.ALLOW, DecisionVerdict.DEFER, DecisionVerdict.BLOCK]
