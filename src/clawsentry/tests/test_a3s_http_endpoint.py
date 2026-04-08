"""Tests for POST /ahp/a3s HTTP endpoint (B-1: a3s-code HTTP transport)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from clawsentry.gateway.models import CanonicalDecision
from clawsentry.gateway.server import SupervisionGateway, create_http_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gateway():
    return SupervisionGateway(trajectory_db_path=":memory:")


@pytest.fixture(autouse=True)
def _isolate_auth_env(monkeypatch):
    """Keep this test module independent from external CS_AUTH_TOKEN state."""
    monkeypatch.delenv("CS_AUTH_TOKEN", raising=False)


@pytest.fixture
def app(gateway):
    return create_http_app(gateway)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _handshake_body(req_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "ahp/handshake",
        "params": {},
    }


def _event_body(
    event_type: str = "pre_action",
    tool_name: str = "Bash",
    command: str = "echo hello",
    session_id: str = "test-session",
    req_id: int = 2,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "ahp/event",
        "params": {
            "event_type": event_type,
            "session_id": session_id,
            "agent_id": "test-agent",
            "payload": {
                "tool": tool_name,
                "command": command,
            },
        },
    }


def _notification_body(event_type: str = "session_start") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "ahp/event",
        "params": {
            "event_type": event_type,
            "session_id": "test-session",
            "payload": {},
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestA3SHttpEndpoint:

    async def test_handshake(self, client):
        resp = await client.post("/ahp/a3s", json=_handshake_body())
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        result = data["result"]
        assert result["protocol_version"] == "2.0"
        assert "pre_action" in result["harness_info"]["capabilities"]

    async def test_safe_command_allowed(self, client):
        resp = await client.post(
            "/ahp/a3s",
            json=_event_body(command="cat README.md", tool_name="Read"),
        )
        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        assert result["action"] in ("continue",)
        assert result["decision"] in ("allow",)

    async def test_jsonrpc_camelcase_event_type_supported(self, client):
        body = _event_body(command="rm -rf /", tool_name="Bash")
        body["params"]["event_type"] = "PreToolUse"

        resp = await client.post("/ahp/a3s", json=body)

        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        assert result["action"] in ("block", "defer")
        assert result["metadata"]["risk_level"] in ("high", "critical")

    async def test_dangerous_command_blocked(self, client):
        resp = await client.post(
            "/ahp/a3s",
            json=_event_body(command="rm -rf /", tool_name="Bash"),
        )
        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        assert result["action"] in ("block", "defer")
        assert result["metadata"]["risk_level"] in ("high", "critical")

    async def test_post_action_allowed(self, client):
        resp = await client.post(
            "/ahp/a3s",
            json=_event_body(event_type="post_action", command="echo done"),
        )
        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        assert result["decision"] == "allow"

    async def test_notification_returns_204(self, client):
        resp = await client.post("/ahp/a3s", json=_notification_body())
        assert resp.status_code == 204

    async def test_invalid_json(self, client):
        resp = await client.post(
            "/ahp/a3s",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_auth_required(self, gateway):
        """When CS_AUTH_TOKEN is set, unauthenticated requests are rejected."""
        import os
        old = os.environ.get("CS_AUTH_TOKEN")
        os.environ["CS_AUTH_TOKEN"] = "test-secret-token-1234567890abcdef"
        try:
            app = create_http_app(gateway)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post("/ahp/a3s", json=_handshake_body())
                assert resp.status_code == 401
        finally:
            if old is None:
                os.environ.pop("CS_AUTH_TOKEN", None)
            else:
                os.environ["CS_AUTH_TOKEN"] = old

    async def test_auth_via_bearer_header(self, gateway):
        import os
        token = "a3s-auth-header-token-1234567890"
        old = os.environ.get("CS_AUTH_TOKEN")
        os.environ["CS_AUTH_TOKEN"] = token
        try:
            app = create_http_app(gateway)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    "/ahp/a3s",
                    json=_handshake_body(),
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 200
        finally:
            if old is None:
                os.environ.pop("CS_AUTH_TOKEN", None)
            else:
                os.environ["CS_AUTH_TOKEN"] = old

    async def test_auth_via_query_token(self, gateway):
        import os
        token = "a3s-auth-query-token-1234567890"
        old = os.environ.get("CS_AUTH_TOKEN")
        os.environ["CS_AUTH_TOKEN"] = token
        try:
            app = create_http_app(gateway)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    f"/ahp/a3s?token={token}",
                    json=_handshake_body(),
                )
                assert resp.status_code == 200
        finally:
            if old is None:
                os.environ.pop("CS_AUTH_TOKEN", None)
            else:
                os.environ["CS_AUTH_TOKEN"] = old

    async def test_payload_too_large_returns_413(self, client):
        huge_command = "x" * (10 * 1024 * 1024 + 1)
        body = _event_body(command=huge_command, tool_name="Bash")
        resp = await client.post("/ahp/a3s", json=body)
        assert resp.status_code == 413

    async def test_trajectory_recorded(self, client, gateway):
        """Events processed via /ahp/a3s are recorded in trajectory store."""
        await client.post(
            "/ahp/a3s",
            json=_event_body(command="ls -la", tool_name="Bash"),
        )
        records = gateway.trajectory_store.records
        assert len(records) >= 1

    async def test_session_registry_updated(self, client, gateway):
        """Events processed via /ahp/a3s update the session registry."""
        await client.post(
            "/ahp/a3s",
            json=_event_body(
                command="cat README.md",
                tool_name="Read",
                session_id="http-session-1",
            ),
        )
        stats = gateway.session_registry.get_session_stats("http-session-1")
        assert stats.get("event_count", 0) >= 1

    async def test_inprocess_adapter_routes_through_gateway(self, client, gateway):
        """Verify InProcessA3SAdapter routes through gateway handle_jsonrpc."""
        # Send two events, verify they both appear in trajectory
        await client.post(
            "/ahp/a3s",
            json=_event_body(command="echo 1", tool_name="Bash", req_id=10),
        )
        await client.post(
            "/ahp/a3s",
            json=_event_body(command="echo 2", tool_name="Bash", req_id=11),
        )
        records = gateway.trajectory_store.records
        assert len(records) >= 2

    async def test_inprocess_adapter_uses_gateway_fallback_decision(self, client, gateway, monkeypatch):
        fallback = CanonicalDecision(
            decision="allow",
            reason="gateway fallback says allow",
            policy_id="gateway-fallback-test",
            risk_level="low",
            decision_source="system",
            final=True,
        )

        async def fake_handle_jsonrpc(_body):
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {
                    "code": -32001,
                    "message": "deadline exceeded",
                    "data": {
                        "rpc_error_code": "DEADLINE_EXCEEDED",
                        "retry_eligible": False,
                        "fallback_decision": fallback.model_dump(mode="json"),
                    },
                },
            }

        monkeypatch.setattr(gateway, "handle_jsonrpc", fake_handle_jsonrpc)

        body = _event_body(
            tool_name="read_file",
            command="",
            session_id="http-fallback-1",
            req_id=99,
        )
        resp = await client.post("/ahp/a3s", json=body)

        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        assert result["decision"] == "allow"
        assert result["action"] == "continue"
        assert result["reason"] == "gateway fallback says allow"
