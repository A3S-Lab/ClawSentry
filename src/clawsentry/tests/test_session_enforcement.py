"""Tests for SessionEnforcementPolicy (A-7)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import patch

import pytest

from clawsentry.gateway.session_enforcement import (
    EnforcementAction,
    EnforcementState,
    SessionEnforcement,
    SessionEnforcementPolicy,
)
from clawsentry.gateway.server import SupervisionGateway


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestSessionEnforcementUnit:
    """Unit tests for SessionEnforcementPolicy core logic."""

    def test_disabled_by_default(self):
        policy = SessionEnforcementPolicy()
        assert policy.enabled is False
        assert policy.check("s1") is None
        assert policy.evaluate_threshold("s1", 10) is None

    def test_below_threshold_no_enforcement(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=3)
        assert policy.evaluate_threshold("s1", 0) is None
        assert policy.evaluate_threshold("s1", 1) is None
        assert policy.evaluate_threshold("s1", 2) is None
        assert policy.check("s1") is None

    def test_breach_threshold_triggers_enforcement(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=3)
        enf = policy.evaluate_threshold("s1", 3)
        assert enf is not None
        assert enf.session_id == "s1"
        assert enf.action == EnforcementAction.DEFER
        assert enf.high_risk_count == 3

    def test_enforcement_persists_after_trigger(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=2, cooldown_seconds=600)
        policy.evaluate_threshold("s1", 2)
        enf = policy.check("s1")
        assert enf is not None
        assert enf.session_id == "s1"

    def test_cooldown_auto_release(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=2, cooldown_seconds=10)
        policy.evaluate_threshold("s1", 2)
        assert policy.check("s1") is not None

        # Fast-forward past cooldown
        enf = policy._enforced["s1"]
        enf.last_high_risk_at = time.monotonic() - 11
        assert policy.check("s1") is None

    def test_cooldown_reset_on_new_high_risk(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=2, cooldown_seconds=10)
        policy.evaluate_threshold("s1", 2)
        old_ts = policy._enforced["s1"].last_high_risk_at

        # New high risk event should NOT create a new trigger but update timestamp
        result = policy.evaluate_threshold("s1", 3)
        assert result is None  # Not a *new* trigger
        assert policy._enforced["s1"].last_high_risk_at >= old_ts
        assert policy._enforced["s1"].high_risk_count == 3

    def test_manual_release(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=2)
        policy.evaluate_threshold("s1", 2)
        assert policy.check("s1") is not None
        assert policy.release("s1") is True
        assert policy.check("s1") is None
        # Double release returns False
        assert policy.release("s1") is False

    def test_action_defer(self):
        policy = SessionEnforcementPolicy(
            enabled=True, threshold=1, action=EnforcementAction.DEFER
        )
        enf = policy.evaluate_threshold("s1", 1)
        assert enf.action == EnforcementAction.DEFER

    def test_action_block(self):
        policy = SessionEnforcementPolicy(
            enabled=True, threshold=1, action=EnforcementAction.BLOCK
        )
        enf = policy.evaluate_threshold("s1", 1)
        assert enf.action == EnforcementAction.BLOCK

    def test_action_l3_require(self):
        policy = SessionEnforcementPolicy(
            enabled=True, threshold=1, action=EnforcementAction.L3_REQUIRE
        )
        enf = policy.evaluate_threshold("s1", 1)
        assert enf.action == EnforcementAction.L3_REQUIRE

    def test_eviction(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=1)
        # Reduce max for test
        import clawsentry.gateway.session_enforcement as mod
        original = mod._MAX_TRACKED_SESSIONS
        mod._MAX_TRACKED_SESSIONS = 3
        try:
            policy.evaluate_threshold("s1", 1)
            policy.evaluate_threshold("s2", 1)
            policy.evaluate_threshold("s3", 1)
            policy.evaluate_threshold("s4", 1)
            assert len(policy._enforced) == 3
            assert "s1" not in policy._enforced
        finally:
            mod._MAX_TRACKED_SESSIONS = original

    def test_get_status_normal(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=5)
        status = policy.get_status("s1")
        assert status["state"] == "normal"
        assert status["session_id"] == "s1"
        assert status["action"] is None

    def test_get_status_enforced(self):
        policy = SessionEnforcementPolicy(enabled=True, threshold=1)
        policy.evaluate_threshold("s1", 1)
        status = policy.get_status("s1")
        assert status["state"] == "enforced"
        assert status["action"] == "defer"
        assert status["high_risk_count"] == 1

    def test_threshold_edge_exact(self):
        """Threshold=3: count=2 should not trigger, count=3 should."""
        policy = SessionEnforcementPolicy(enabled=True, threshold=3)
        assert policy.evaluate_threshold("s1", 2) is None
        enf = policy.evaluate_threshold("s1", 3)
        assert enf is not None
        assert enf.high_risk_count == 3


# ---------------------------------------------------------------------------
# Integration tests — through SupervisionGateway.handle_jsonrpc
# ---------------------------------------------------------------------------

def _build_jsonrpc(session_id: str, tool_name: str, command: str, req_id: int = 1) -> bytes:
    """Build a JSON-RPC 2.0 sync_decision request for a pre_action event."""
    return json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "ahp/sync_decision",
        "params": {
            "request_id": f"test-{session_id}-{req_id}",
            "rpc_version": "sync_decision.1.0",
            "deadline_ms": 5000,
            "decision_tier": "L1",
            "event": {
                "schema_version": "ahp.1.0",
                "event_id": f"evt-{session_id}-{req_id}",
                "trace_id": f"trace-{session_id}",
                "event_type": "pre_action",
                "session_id": session_id,
                "agent_id": "test-agent",
                "source_framework": "test",
                "occurred_at": "2026-03-22T00:00:00Z",
                "payload": {"command": command},
                "tool_name": tool_name,
                "risk_hints": ["destructive_pattern", "shell_execution"] if "rm" in command or "chmod" in command else [],
            },
            "context": {
                "caller_adapter": "test-integration",
            },
        },
    }).encode("utf-8")


def _build_post_action_jsonrpc(session_id: str, req_id: int = 100) -> bytes:
    """Build a JSON-RPC for a post_action event."""
    return json.dumps({
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "ahp/sync_decision",
        "params": {
            "request_id": f"test-post-{session_id}-{req_id}",
            "rpc_version": "sync_decision.1.0",
            "deadline_ms": 5000,
            "decision_tier": "L1",
            "event": {
                "schema_version": "ahp.1.0",
                "event_id": f"evt-post-{session_id}-{req_id}",
                "trace_id": f"trace-{session_id}",
                "event_type": "post_action",
                "session_id": session_id,
                "agent_id": "test-agent",
                "source_framework": "test",
                "occurred_at": "2026-03-22T00:00:00Z",
                "payload": {"result": "ok"},
                "tool_name": "Bash",
            },
            "context": {
                "caller_adapter": "test-integration",
            },
        },
    }).encode("utf-8")


class TestSessionEnforcementIntegration:
    """Integration tests using SupervisionGateway.handle_jsonrpc end-to-end."""

    @pytest.fixture
    def gateway_enforced(self):
        """Gateway with enforcement enabled, threshold=3, action=defer."""
        policy = SessionEnforcementPolicy(
            enabled=True, threshold=3, action=EnforcementAction.DEFER, cooldown_seconds=600
        )
        return SupervisionGateway(
            trajectory_db_path=":memory:",
            session_enforcement=policy,
        )

    async def test_enforcement_override_after_threshold(self, gateway_enforced):
        """Send 3 high-risk pre_action → 4th is overridden to defer."""
        gw = gateway_enforced
        # Send 3 dangerous commands (these are processed normally by L1)
        for i in range(1, 4):
            resp = await gw.handle_jsonrpc(
                _build_jsonrpc("s1", "Bash", f"rm -rf /data{i}", req_id=i)
            )
            result = resp["result"]
            decision = result["decision"]
            # L1 should block these normally
            assert decision["decision"] in ("block", "defer"), f"Event {i}: {decision}"

        # 4th event should be enforcement-overridden
        resp4 = await gw.handle_jsonrpc(
            _build_jsonrpc("s1", "Bash", "rm -rf /data4", req_id=4)
        )
        result4 = resp4["result"]
        decision4 = result4["decision"]
        assert decision4["decision"] == "defer"
        assert "session-enforcement-A7" in decision4["policy_id"]

    async def test_post_action_not_affected_by_enforcement(self, gateway_enforced):
        """Post-action events should still be ALLOW even when session is enforced."""
        gw = gateway_enforced
        # Trigger enforcement
        for i in range(1, 4):
            await gw.handle_jsonrpc(
                _build_jsonrpc("s1", "Bash", f"rm -rf /x{i}", req_id=i)
            )

        # Post-action should still be allowed
        resp = await gw.handle_jsonrpc(_build_post_action_jsonrpc("s1"))
        decision = resp["result"]["decision"]
        assert decision["decision"] == "allow"

    async def test_event_bus_enforcement_change(self, gateway_enforced):
        """EventBus should receive session_enforcement_change on trigger."""
        gw = gateway_enforced
        sub_id, queue = gw.event_bus.subscribe(
            event_types={"session_enforcement_change"}
        )
        assert sub_id is not None

        # Trigger enforcement with 3 high-risk events
        for i in range(1, 4):
            await gw.handle_jsonrpc(
                _build_jsonrpc("s1", "Bash", f"rm -rf /e{i}", req_id=i)
            )

        # Check that we got the enforcement change event
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        enforcement_events = [e for e in events if e.get("type") == "session_enforcement_change"]
        assert len(enforcement_events) >= 1
        enf_evt = enforcement_events[0]
        assert enf_evt["session_id"] == "s1"
        assert enf_evt["state"] == "enforced"
        assert enf_evt["action"] == "defer"

        gw.event_bus.unsubscribe(sub_id)

    async def test_release_restores_normal(self, gateway_enforced):
        """After manual release, decisions should go back to normal L1."""
        gw = gateway_enforced
        # Trigger enforcement
        for i in range(1, 4):
            await gw.handle_jsonrpc(
                _build_jsonrpc("s1", "Bash", f"rm -rf /r{i}", req_id=i)
            )

        # Verify enforced
        status = gw.session_enforcement.get_status("s1")
        assert status["state"] == "enforced"

        # Release
        assert gw.session_enforcement.release("s1") is True
        status = gw.session_enforcement.get_status("s1")
        assert status["state"] == "normal"

        # Next event should be processed normally by L1 (not enforcement)
        resp = await gw.handle_jsonrpc(
            _build_jsonrpc("s1", "Read", "cat /etc/hosts", req_id=10)
        )
        decision = resp["result"]["decision"]
        # Should NOT have session-enforcement policy_id
        assert "session-enforcement" not in decision.get("policy_id", "")

    async def test_disabled_enforcement_no_change(self):
        """When enforcement is disabled, behavior is identical to baseline."""
        gw = SupervisionGateway(
            trajectory_db_path=":memory:",
            session_enforcement=SessionEnforcementPolicy(enabled=False),
        )
        # Send many dangerous events
        for i in range(1, 6):
            resp = await gw.handle_jsonrpc(
                _build_jsonrpc("s1", "Bash", f"rm -rf /d{i}", req_id=i)
            )
            result = resp["result"]
            decision = result["decision"]
            # L1 blocks these, but no enforcement override
            assert "session-enforcement" not in decision.get("policy_id", "")
