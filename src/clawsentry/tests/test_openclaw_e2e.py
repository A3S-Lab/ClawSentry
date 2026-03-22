"""
End-to-end integration tests — Gate 7 verification (Phase 2).

Covers: Webhook safe/dangerous commands, approval states,
Gateway fallback, cross-framework sharing,
non-blocking event types (#33).
"""

import asyncio
import hmac
import hashlib
import json
import os
import time
import pytest
import pytest_asyncio
import httpx

from clawsentry.gateway.server import SupervisionGateway, start_uds_server
from clawsentry.gateway.models import (
    DecisionVerdict,
    DecisionSource,
    DecisionContext,
    AgentTrustLevel,
)
from clawsentry.adapters.openclaw_adapter import OpenClawAdapter, OpenClawAdapterConfig
from clawsentry.adapters.openclaw_gateway_client import OpenClawGatewayClient
from clawsentry.adapters.openclaw_normalizer import OpenClawNormalizer
from clawsentry.adapters.openclaw_webhook_receiver import create_webhook_app
from clawsentry.adapters.webhook_security import WebhookSecurityConfig
from clawsentry.adapters.a3s_adapter import A3SCodeAdapter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

E2E_UDS_PATH = "/tmp/ahp-oc-e2e-test.sock"
WEBHOOK_SECRET = "e2e-test-secret"
WEBHOOK_TOKEN = "e2e-test-token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sign(secret: str, ts: int, body: bytes) -> str:
    msg = f"{ts}.".encode() + body
    return f"v1={hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()}"


def _webhook_headers(body: bytes) -> dict:
    ts = int(time.time())
    return {
        "Authorization": f"Bearer {WEBHOOK_TOKEN}",
        "X-AHP-Signature": _sign(WEBHOOK_SECRET, ts, body),
        "X-AHP-Timestamp": str(ts),
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def e2e_gateway():
    gw = SupervisionGateway()
    server = await start_uds_server(gw, E2E_UDS_PATH)
    yield gw
    server.close()
    await server.wait_closed()
    if os.path.exists(E2E_UDS_PATH):
        os.unlink(E2E_UDS_PATH)


@pytest.fixture
def e2e_client(e2e_gateway):
    return OpenClawGatewayClient(
        uds_path=E2E_UDS_PATH,
        default_deadline_ms=500,
    )


@pytest.fixture
def e2e_adapter(e2e_client):
    config = OpenClawAdapterConfig(
        source_protocol_version="1.0",
        git_short_sha="e2etest",
        webhook_token=WEBHOOK_TOKEN,
        webhook_secret=WEBHOOK_SECRET,
        require_https=False,
    )
    return OpenClawAdapter(config=config, gateway_client=e2e_client)


@pytest.fixture
def e2e_webhook_app(e2e_client):
    sec_config = WebhookSecurityConfig(
        primary_token=WEBHOOK_TOKEN,
        webhook_secret=WEBHOOK_SECRET,
        require_https=False,
    )
    normalizer = OpenClawNormalizer(
        source_protocol_version="1.0",
        git_short_sha="e2etest",
    )
    return create_webhook_app(sec_config, normalizer, e2e_client)


# ===========================================================================
# E2E: Hook Collector — Safe Command
# ===========================================================================

class TestE2EHookSafeCommand:
    @pytest.mark.asyncio
    async def test_read_file_allowed(self, e2e_adapter):
        decision = await e2e_adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-safe", "tool": "read_file", "path": "/tmp/readme"},
            session_id="oc-e2e-1",
            agent_id="oc-agent-1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.ALLOW


# ===========================================================================
# E2E: Hook Collector — Dangerous Command
# ===========================================================================

class TestE2EHookDangerousCommand:
    @pytest.mark.asyncio
    async def test_rm_rf_blocked(self, e2e_adapter):
        decision = await e2e_adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-danger", "tool": "bash", "command": "rm -rf /"},
            session_id="oc-e2e-2",
            agent_id="oc-agent-1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.BLOCK


# ===========================================================================
# E2E: Webhook — Full Chain
# ===========================================================================

class TestE2EWebhook:
    @pytest.mark.asyncio
    async def test_webhook_safe_command_allow(self, e2e_webhook_app):
        body = json.dumps({
            "type": "exec.approval.requested",
            "sessionKey": "oc-e2e-wh-1",
            "agentId": "oc-agent-1",
            "payload": {"approval_id": "ap-wh-safe", "tool": "read_file", "path": "/tmp/x"},
        }).encode()
        transport = httpx.ASGITransport(app=e2e_webhook_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/webhook/openclaw", content=body, headers=_webhook_headers(body)
            )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "allow"

    @pytest.mark.asyncio
    async def test_webhook_dangerous_command_block(self, e2e_webhook_app):
        body = json.dumps({
            "type": "exec.approval.requested",
            "sessionKey": "oc-e2e-wh-2",
            "agentId": "oc-agent-1",
            "payload": {"approval_id": "ap-wh-danger", "tool": "bash", "command": "rm -rf /"},
        }).encode()
        transport = httpx.ASGITransport(app=e2e_webhook_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/webhook/openclaw", content=body, headers=_webhook_headers(body)
            )
        assert resp.status_code == 200
        assert resp.json()["decision"] == "block"


# ===========================================================================
# E2E: Gateway Down Fallback
# ===========================================================================

class TestE2EFallback:
    @pytest.mark.asyncio
    async def test_gateway_down_dangerous_blocks(self):
        config = OpenClawAdapterConfig(
            source_protocol_version="1.0",
            git_short_sha="e2etest",
        )
        client = OpenClawGatewayClient(
            uds_path="/tmp/nonexistent-oc-e2e.sock",
            http_url="http://127.0.0.1:19999/ahp",
        )
        adapter = OpenClawAdapter(config=config, gateway_client=client)
        decision = await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-fb", "tool": "bash", "command": "rm -rf /"},
            session_id="oc-fb-1",
            agent_id="oc-agent-1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.BLOCK


# ===========================================================================
# E2E: Cross-Framework (A3S + OpenClaw sharing same Gateway)
# ===========================================================================

class TestE2ECrossFramework:
    @pytest.mark.asyncio
    async def test_both_adapters_share_gateway(self, e2e_gateway, e2e_adapter):
        """Both A3S and OpenClaw adapters should work with the same Gateway."""
        # OpenClaw request
        oc_decision = await e2e_adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-cross", "tool": "read_file", "path": "/tmp/x"},
            session_id="cross-oc",
            agent_id="cross-agent",
        )
        assert oc_decision.decision == DecisionVerdict.ALLOW

        # A3S request through same Gateway
        a3s_adapter = A3SCodeAdapter(uds_path=E2E_UDS_PATH, default_deadline_ms=500)
        evt = a3s_adapter.normalize_hook_event(
            "PreToolUse",
            {"tool": "read_file", "path": "/tmp/readme"},
            session_id="cross-a3s",
            agent_id="cross-agent",
        )
        a3s_decision = await a3s_adapter.request_decision(evt)
        assert a3s_decision.decision == DecisionVerdict.ALLOW

        # Both should be in trajectory
        assert e2e_gateway.trajectory_store.count() >= 2


# ===========================================================================
# E2E: Trajectory Recording
# ===========================================================================

class TestE2ETrajectory:
    @pytest.mark.asyncio
    async def test_openclaw_trajectory_recorded(self, e2e_gateway, e2e_adapter):
        initial = e2e_gateway.trajectory_store.count()
        await e2e_adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-traj", "tool": "read_file", "path": "/tmp/x"},
            session_id="oc-traj-1",
            agent_id="oc-agent-1",
        )
        assert e2e_gateway.trajectory_store.count() == initial + 1
        record = e2e_gateway.trajectory_store.records[-1]
        assert record["event"]["source_framework"] == "openclaw"


# ===========================================================================
# E2E: Non-blocking Event Types (#33)
# ===========================================================================

class TestE2ENonBlockingOpenClaw:
    @pytest.mark.asyncio
    async def test_session_compact_event_allowed(self, e2e_adapter):
        """session:compact:after should ALLOW as non-blocking."""
        decision = await e2e_adapter.handle_hook_event(
            event_type="session:compact:after",
            payload={"summary": "compacted 200 messages to 50"},
            session_id="oc-nb-1",
            agent_id="oc-agent-1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.ALLOW
        assert decision.final is True

    @pytest.mark.asyncio
    async def test_command_new_session_event_allowed(self, e2e_adapter):
        """command:new (SESSION type) should ALLOW."""
        decision = await e2e_adapter.handle_hook_event(
            event_type="command:new",
            payload={"command": "/help"},
            session_id="oc-nb-2",
            agent_id="oc-agent-1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.ALLOW

    @pytest.mark.asyncio
    async def test_chat_final_post_response_allowed(self, e2e_adapter):
        """chat final (POST_RESPONSE) should ALLOW as observation-only."""
        decision = await e2e_adapter.handle_hook_event(
            event_type="chat",
            payload={"state": "final", "text": "Here is the answer."},
            session_id="oc-nb-3",
            agent_id="oc-agent-1",
            run_id="run-chat-1",
            source_seq=1,
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.ALLOW

    @pytest.mark.asyncio
    async def test_chat_error_event_allowed(self, e2e_adapter):
        """chat error (ERROR type) should ALLOW as observation-only."""
        decision = await e2e_adapter.handle_hook_event(
            event_type="chat",
            payload={"state": "error", "error": "rate limit exceeded"},
            session_id="oc-nb-4",
            agent_id="oc-agent-1",
            run_id="run-chat-2",
            source_seq=2,
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.ALLOW

    @pytest.mark.asyncio
    async def test_exec_approval_resolved_post_action_allowed(self, e2e_adapter):
        """exec.approval.resolved (POST_ACTION) should ALLOW even for dangerous tools."""
        decision = await e2e_adapter.handle_hook_event(
            event_type="exec.approval.resolved",
            payload={"approval_id": "ap-resolved-1", "tool": "bash", "result": "rm: cannot remove"},
            session_id="oc-nb-5",
            agent_id="oc-agent-1",
        )
        assert decision is not None
        assert decision.decision == DecisionVerdict.ALLOW

    @pytest.mark.asyncio
    async def test_nonblocking_event_trajectory_recorded(self, e2e_gateway, e2e_adapter):
        """Non-blocking OpenClaw events should be recorded in trajectory."""
        initial = e2e_gateway.trajectory_store.count()
        await e2e_adapter.handle_hook_event(
            event_type="command:new",
            payload={"command": "/status"},
            session_id="oc-nb-traj",
            agent_id="oc-agent-1",
        )
        assert e2e_gateway.trajectory_store.count() == initial + 1
        record = e2e_gateway.trajectory_store.records[-1]
        assert record["event"]["source_framework"] == "openclaw"
        assert record["event"]["event_type"] == "session"


# ===========================================================================
# E2E: ApprovalStateMachine Lifecycle (#33)
# ===========================================================================

class TestE2EApprovalLifecycle:
    @pytest.mark.asyncio
    async def test_approval_allow_lifecycle(self, e2e_adapter):
        """Full lifecycle: requested -> pending -> terminal_allow via gateway."""
        decision = await e2e_adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-lc-1", "tool": "read_file", "path": "/tmp/x"},
            session_id="lc-sess-1",
            agent_id="lc-agent-1",
        )
        assert decision.decision == DecisionVerdict.ALLOW

        record = e2e_adapter.approval_sm.get("ap-lc-1")
        assert record is not None
        assert record.final is True
        assert record.decision_mapped == DecisionVerdict.ALLOW

    @pytest.mark.asyncio
    async def test_approval_block_lifecycle(self, e2e_adapter):
        """Full lifecycle: requested -> pending -> terminal_block via gateway."""
        decision = await e2e_adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-lc-2", "tool": "bash", "command": "rm -rf /"},
            session_id="lc-sess-2",
            agent_id="lc-agent-1",
        )
        assert decision.decision == DecisionVerdict.BLOCK

        record = e2e_adapter.approval_sm.get("ap-lc-2")
        assert record is not None
        assert record.final is True
        assert record.decision_mapped == DecisionVerdict.BLOCK

    @pytest.mark.asyncio
    async def test_approval_gateway_down_no_route(self):
        """When gateway is down, approval should go to no_route path."""
        config = OpenClawAdapterConfig(
            source_protocol_version="1.0",
            git_short_sha="e2etest",
        )
        client = OpenClawGatewayClient(
            uds_path="/tmp/nonexistent-lc.sock",
            http_url="http://127.0.0.1:19999/ahp",
        )
        adapter = OpenClawAdapter(config=config, gateway_client=client)
        decision = await adapter.handle_hook_event(
            event_type="exec.approval.requested",
            payload={"approval_id": "ap-lc-3", "tool": "bash", "command": "rm -rf /"},
            session_id="lc-sess-3",
            agent_id="lc-agent-1",
        )
        assert decision.decision == DecisionVerdict.BLOCK

        record = adapter.approval_sm.get("ap-lc-3")
        assert record is not None
        assert record.final is True
