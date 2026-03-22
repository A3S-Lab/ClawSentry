"""
Tests for OpenClaw Adapter main entry — Gate 6 verification.

Covers: Adapter composition, Hook Collector, invalid_event channel, config.
"""

import pytest
from unittest.mock import AsyncMock

from clawsentry.adapters.openclaw_adapter import OpenClawAdapter, OpenClawAdapterConfig
from clawsentry.gateway.models import (
    CanonicalDecision,
    DecisionVerdict,
    DecisionSource,
    FailureClass,
    RiskLevel,
    EventType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def adapter_config():
    return OpenClawAdapterConfig(
        source_protocol_version="1.0",
        git_short_sha="abc1234",
        webhook_token="tok-test",
        require_https=False,
    )


@pytest.fixture
def mock_gateway_client():
    client = AsyncMock()
    client.request_decision.return_value = CanonicalDecision(
        decision=DecisionVerdict.ALLOW,
        reason="test allow",
        policy_id="test-policy",
        risk_level=RiskLevel.LOW,
        decision_source=DecisionSource.POLICY,
        final=True,
    )
    return client


@pytest.fixture
def adapter(adapter_config, mock_gateway_client):
    return OpenClawAdapter(config=adapter_config, gateway_client=mock_gateway_client)


# ===========================================================================
# Hook Collector
# ===========================================================================

class TestHookCollector:
    @pytest.mark.asyncio
    async def test_handle_hook_event(self, adapter, mock_gateway_client):
        decision = await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-1", "tool": "bash", "command": "ls"},
            session_id="s1",
            agent_id="a1",
        )
        assert decision.decision == DecisionVerdict.ALLOW
        mock_gateway_client.request_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_unmapped_event_returns_none(self, adapter, mock_gateway_client):
        decision = await adapter.handle_hook_event(
            event_type="completely:unknown",
            payload={},
            session_id="s1",
            agent_id="a1",
        )
        assert decision is None
        mock_gateway_client.request_decision.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_event_normalizes(self, adapter, mock_gateway_client):
        decision = await adapter.handle_hook_event(
            event_type="command:new",
            payload={"command": "test"},
            session_id="s1",
            agent_id="a1",
        )
        assert decision is not None


# ===========================================================================
# Invalid Event Channel
# ===========================================================================

class TestInvalidEventChannel:
    @pytest.mark.asyncio
    async def test_invalid_event_logged(self, adapter):
        """Hook exceptions should not crash, and event should be logged."""
        # Force normalization to produce event but gateway to fail
        adapter._gateway_client.request_decision.side_effect = Exception("gateway error")
        decision = await adapter.handle_hook_event(
            event_type="message:received",
            payload={"text": "hi"},
            session_id="s1",
            agent_id="a1",
        )
        # Should return None (error handled gracefully)
        assert decision is None
        assert adapter.invalid_event_count >= 1

    @pytest.mark.asyncio
    async def test_invalid_event_summary_contains_fingerprint(self, adapter):
        adapter._gateway_client.request_decision.side_effect = Exception("gateway error")
        await adapter.handle_hook_event(
            event_type="message:received",
            payload={"text": "hi"},
            session_id="s1",
            agent_id="a1",
        )
        assert len(adapter.invalid_event_summaries) == 1
        summary = adapter.invalid_event_summaries[0]
        assert summary["event_type"] == "message:received"
        assert len(summary["fingerprint"]) == 64

    @pytest.mark.asyncio
    async def test_medium_or_higher_invalid_event_enters_manual_review_queue(self, adapter):
        adapter._gateway_client.request_decision.side_effect = Exception("gateway error")
        await adapter.handle_hook_event(
            event_type="message:received",
            payload={"text": "hi", "risk_level": "high"},
            session_id="s1",
            agent_id="a1",
        )
        assert len(adapter.manual_review_queue) == 1
        item = adapter.manual_review_queue[0]
        assert item["risk_level"] == "high"
        assert item["event_type"] == "message:received"

    @pytest.mark.asyncio
    async def test_invalid_event_count_over_20_per_minute_triggers_critical_alert(self, adapter):
        adapter._gateway_client.request_decision.side_effect = Exception("gateway error")

        for i in range(21):
            await adapter.handle_hook_event(
                event_type="message:received",
                payload={"text": f"msg-{i}", "risk_level": "low"},
                session_id="s1",
                agent_id="a1",
            )

        assert any(
            alert["metric"] == "invalid_event_count_1m" and alert["severity"] == "critical"
            for alert in adapter.invalid_event_alerts
        )

    @pytest.mark.asyncio
    async def test_invalid_event_rate_over_1_percent_5m_triggers_critical_alert(
        self, adapter, mock_gateway_client
    ):
        counter = {"n": 0}
        allow_decision = mock_gateway_client.request_decision.return_value

        async def _side_effect(_event):
            counter["n"] += 1
            if counter["n"] <= 2:
                raise Exception("gateway error")
            return allow_decision

        adapter._gateway_client.request_decision.side_effect = _side_effect
        for i in range(100):
            await adapter.handle_hook_event(
                event_type="message:received",
                payload={"text": f"msg-{i}", "risk_level": "low"},
                session_id="s1",
                agent_id="a1",
            )

        assert any(
            alert["metric"] == "invalid_event_rate_5m" and alert["severity"] == "critical"
            for alert in adapter.invalid_event_alerts
        )


# ===========================================================================
# Adapter Properties
# ===========================================================================

class TestAdapterProperties:
    def test_adapter_has_normalizer(self, adapter):
        assert adapter.normalizer is not None
        assert adapter.normalizer.SOURCE_FRAMEWORK == "openclaw"

    def test_adapter_has_approval_state_machine(self, adapter):
        assert adapter.approval_sm is not None

    def test_adapter_config(self, adapter):
        assert adapter.config.source_protocol_version == "1.0"


# ===========================================================================
# ApprovalStateMachine Integration (#33)
# ===========================================================================

class TestApprovalSMIntegration:
    @pytest.mark.asyncio
    async def test_approval_requested_creates_sm_record(self, adapter, mock_gateway_client):
        """exec.approval.requested should create an ApprovalRecord via SM."""
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-sm-1", "tool": "read_file", "path": "/tmp/x"},
            session_id="sm-sess-1",
            agent_id="sm-agent-1",
        )
        record = adapter.approval_sm.get("ap-sm-1")
        assert record is not None
        assert record.final is True
        assert record.decision_mapped == DecisionVerdict.ALLOW

    @pytest.mark.asyncio
    async def test_approval_block_creates_terminal_block(self, adapter_config):
        """When gateway blocks, approval should reach terminal_block."""
        mock_client = AsyncMock()
        mock_client.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.BLOCK,
            reason="dangerous command",
            policy_id="test-policy",
            risk_level=RiskLevel.HIGH,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        adapter = OpenClawAdapter(config=adapter_config, gateway_client=mock_client)
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-sm-2", "tool": "bash", "command": "rm -rf /"},
            session_id="sm-sess-2",
            agent_id="sm-agent-1",
        )
        record = adapter.approval_sm.get("ap-sm-2")
        assert record is not None
        assert record.final is True
        assert record.decision_mapped == DecisionVerdict.BLOCK

    @pytest.mark.asyncio
    async def test_non_approval_event_skips_sm(self, adapter, mock_gateway_client):
        """Non-approval events (no approval_id) should not create SM records."""
        await adapter.handle_hook_event(
            event_type="command:new",
            payload={"command": "/help"},
            session_id="sm-sess-3",
            agent_id="sm-agent-1",
        )
        assert len(adapter.approval_sm._records) == 0

    @pytest.mark.asyncio
    async def test_gateway_failure_triggers_no_route(self, adapter_config):
        """When gateway fails for approval event, SM should go to no_route."""
        mock_client = AsyncMock()
        mock_client.request_decision.side_effect = Exception("gateway down")
        adapter = OpenClawAdapter(config=adapter_config, gateway_client=mock_client)
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-sm-3", "tool": "bash", "command": "rm -rf /"},
            session_id="sm-sess-4",
            agent_id="sm-agent-1",
        )
        record = adapter.approval_sm.get("ap-sm-3")
        assert record is not None
        # high risk + no_route → terminal_block
        assert record.final is True

    @pytest.mark.asyncio
    async def test_invalid_event_lists_bounded_by_cap(self, adapter):
        """W-1: Burst of invalid events should be capped by MAX_RAW_EVENTS."""
        adapter._gateway_client.request_decision.side_effect = Exception("gw err")
        # Use tiny caps for testing
        adapter._invalid_channel.MAX_RAW_EVENTS = 5
        adapter._invalid_channel.MAX_SUMMARIES = 5
        adapter._invalid_channel.MAX_REVIEW_QUEUE = 5
        adapter._invalid_channel.MAX_ALERTS = 5

        for i in range(20):
            await adapter.handle_hook_event(
                event_type="message:received",
                payload={"text": f"msg-{i}", "risk_level": "high"},
                session_id="s1",
                agent_id="a1",
            )

        assert adapter._invalid_channel.invalid_count() <= 5
        assert len(adapter._invalid_channel.summaries) <= 5
        assert len(adapter._invalid_channel.manual_review_queue) <= 5
        assert len(adapter._invalid_channel.alerts) <= 5


# ===========================================================================
# Enforcement Callback (Phase 5.5)
# ===========================================================================

class TestEnforcementCallback:
    """Test that adapter dispatches resolve calls via ApprovalClient."""

    @pytest.fixture
    def mock_approval_client(self):
        client = AsyncMock()
        client.resolve = AsyncMock(return_value=True)
        client._config = type("C", (), {"enabled": True})()
        return client

    @pytest.fixture
    def enforced_adapter(self, adapter_config, mock_approval_client):
        mock_gw = AsyncMock()
        mock_gw.request_decision = AsyncMock(
            return_value=CanonicalDecision(
                decision=DecisionVerdict.BLOCK,
                reason="dangerous",
                policy_id="test-policy",
                risk_level=RiskLevel.HIGH,
                decision_source=DecisionSource.POLICY,
                final=True,
            )
        )
        adapter = OpenClawAdapter(
            config=adapter_config,
            gateway_client=mock_gw,
            approval_client=mock_approval_client,
        )
        return adapter, mock_approval_client, mock_gw

    @pytest.mark.asyncio
    async def test_block_triggers_deny_callback(self, enforced_adapter):
        adapter, mock_client, _ = enforced_adapter
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-1", "tool": "bash", "command": "rm -rf /"},
            session_id="s1",
            agent_id="a1",
        )
        mock_client.resolve.assert_awaited_once_with(
            "ap-enf-1", "deny", reason="dangerous"
        )

    @pytest.mark.asyncio
    async def test_allow_triggers_allow_once_callback(self, enforced_adapter):
        adapter, mock_client, mock_gw = enforced_adapter
        mock_gw.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.ALLOW,
            reason="safe",
            policy_id="test-policy",
            risk_level=RiskLevel.LOW,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-2", "tool": "Read", "command": "cat f.txt"},
            session_id="s1",
            agent_id="a1",
        )
        mock_client.resolve.assert_awaited_once_with(
            "ap-enf-2", "allow-once", reason="safe"
        )

    @pytest.mark.asyncio
    async def test_defer_no_callback(self, enforced_adapter):
        adapter, mock_client, mock_gw = enforced_adapter
        mock_gw.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.DEFER,
            reason="needs review",
            policy_id="test-policy",
            risk_level=RiskLevel.MEDIUM,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-3", "tool": "Write"},
            session_id="s1",
            agent_id="a1",
        )
        mock_client.resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_approval_id_no_callback(self, enforced_adapter):
        adapter, mock_client, mock_gw = enforced_adapter
        mock_gw.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.ALLOW,
            reason="ok",
            policy_id="test-policy",
            risk_level=RiskLevel.LOW,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        await adapter.handle_hook_event(
            event_type="message:received",
            payload={"text": "hello"},
            session_id="s1",
            agent_id="a1",
            run_id="r1",
            source_seq=1,
        )
        mock_client.resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_client_backward_compat(self, adapter_config):
        """Adapter without approval_client works (backward compat)."""
        mock_gw = AsyncMock()
        mock_gw.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.ALLOW,
            reason="ok",
            policy_id="test-policy",
            risk_level=RiskLevel.LOW,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        adapter = OpenClawAdapter(config=adapter_config, gateway_client=mock_gw)
        decision = await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-4", "tool": "Read"},
            session_id="s1",
            agent_id="a1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.ALLOW

    @pytest.mark.asyncio
    async def test_enforcement_block_passes_reason(self, enforced_adapter):
        """BLOCK resolve includes reason string."""
        adapter, mock_client, _ = enforced_adapter
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-reason-1", "tool": "bash", "command": "rm -rf /"},
            session_id="s1",
            agent_id="a1",
        )
        mock_client.resolve.assert_awaited_once()
        call_kwargs = mock_client.resolve.call_args
        # reason kwarg must be present and non-empty
        assert "reason" in call_kwargs.kwargs
        reason = call_kwargs.kwargs["reason"]
        assert isinstance(reason, str) and len(reason) > 0
        # The decision reason is "dangerous" from fixture
        assert reason == "dangerous"

    @pytest.mark.asyncio
    async def test_enforcement_allow_passes_reason(self, enforced_adapter):
        """ALLOW resolve includes reason string."""
        adapter, mock_client, mock_gw = enforced_adapter
        mock_gw.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.ALLOW,
            reason="safe command",
            policy_id="test-policy",
            risk_level=RiskLevel.LOW,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-reason-2", "tool": "Read", "command": "cat f.txt"},
            session_id="s1",
            agent_id="a1",
        )
        mock_client.resolve.assert_awaited_once()
        call_kwargs = mock_client.resolve.call_args
        assert "reason" in call_kwargs.kwargs
        reason = call_kwargs.kwargs["reason"]
        assert isinstance(reason, str) and len(reason) > 0
        assert reason == "safe command"

    @pytest.mark.asyncio
    async def test_enforcement_empty_reason_builds_default(self, enforced_adapter):
        """When decision.reason is empty, a default reason is built."""
        adapter, mock_client, mock_gw = enforced_adapter
        mock_gw.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.BLOCK,
            reason="",
            policy_id="test-policy",
            risk_level=RiskLevel.HIGH,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-reason-3", "tool": "bash", "command": "rm -rf /"},
            session_id="s1",
            agent_id="a1",
        )
        mock_client.resolve.assert_awaited_once()
        call_kwargs = mock_client.resolve.call_args
        reason = call_kwargs.kwargs["reason"]
        assert "blocked" in reason.lower()
        assert "high" in reason.lower()

    @pytest.mark.asyncio
    async def test_enforcement_allow_empty_reason_builds_default(self, enforced_adapter):
        """When decision.reason is empty for ALLOW, a default reason is built."""
        adapter, mock_client, mock_gw = enforced_adapter
        mock_gw.request_decision.return_value = CanonicalDecision(
            decision=DecisionVerdict.ALLOW,
            reason="",
            policy_id="test-policy",
            risk_level=RiskLevel.LOW,
            decision_source=DecisionSource.POLICY,
            final=True,
        )
        await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-reason-4", "tool": "Read", "command": "cat f.txt"},
            session_id="s1",
            agent_id="a1",
        )
        mock_client.resolve.assert_awaited_once()
        call_kwargs = mock_client.resolve.call_args
        reason = call_kwargs.kwargs["reason"]
        assert "allowed" in reason.lower()
        assert "low" in reason.lower()

    @pytest.mark.asyncio
    async def test_callback_failure_does_not_break_flow(self, enforced_adapter):
        """If approval_client.resolve raises, the decision still returns."""
        adapter, mock_client, _ = enforced_adapter
        mock_client.resolve.side_effect = Exception("WS connection lost")
        decision = await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-enf-5", "tool": "bash", "command": "rm -rf /"},
            session_id="s1",
            agent_id="a1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.BLOCK
