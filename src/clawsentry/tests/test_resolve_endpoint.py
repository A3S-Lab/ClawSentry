"""Tests for POST /ahp/resolve endpoint."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from clawsentry.gateway.server import SupervisionGateway, create_http_app
from clawsentry.gateway.stack import add_resolve_endpoint, _build_openclaw_runtime


class TestResolveEndpoint:
    """POST /ahp/resolve proxies to OpenClaw approval client."""

    @pytest.fixture
    def gateway(self, tmp_path):
        return SupervisionGateway(trajectory_db_path=str(tmp_path / "traj.db"))

    @pytest.fixture
    def mock_approval_client(self):
        client = AsyncMock()
        client.resolve = AsyncMock(return_value=True)
        return client

    @pytest.fixture
    def app_with_resolve(self, gateway, mock_approval_client):
        app = create_http_app(gateway)
        add_resolve_endpoint(app, mock_approval_client)
        return app

    @pytest.fixture
    def app_without_resolve(self, gateway):
        app = create_http_app(gateway)
        add_resolve_endpoint(app, None)
        return app

    @pytest.mark.asyncio
    async def test_resolve_allow(self, app_with_resolve, mock_approval_client):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_resolve),
            base_url="http://test",
        ) as client:
            resp = await client.post("/ahp/resolve", json={
                "approval_id": "ap-123",
                "decision": "allow-once",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        mock_approval_client.resolve.assert_awaited_once_with(
            "ap-123", "allow-once", reason="",
        )

    @pytest.mark.asyncio
    async def test_resolve_deny_with_reason(self, app_with_resolve, mock_approval_client):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_resolve),
            base_url="http://test",
        ) as client:
            resp = await client.post("/ahp/resolve", json={
                "approval_id": "ap-456",
                "decision": "deny",
                "reason": "operator denied via dashboard",
            })
        assert resp.status_code == 200
        mock_approval_client.resolve.assert_awaited_once_with(
            "ap-456", "deny", reason="operator denied via dashboard",
        )

    @pytest.mark.asyncio
    async def test_resolve_unavailable_without_client(self, app_without_resolve):
        async with AsyncClient(
            transport=ASGITransport(app=app_without_resolve),
            base_url="http://test",
        ) as client:
            resp = await client.post("/ahp/resolve", json={
                "approval_id": "ap-789",
                "decision": "deny",
            })
        assert resp.status_code == 503
        assert "not available" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_resolve_missing_fields(self, app_with_resolve):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_resolve),
            base_url="http://test",
        ) as client:
            resp = await client.post("/ahp/resolve", json={"approval_id": "ap-1"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_resolve_invalid_decision(self, app_with_resolve):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_resolve),
            base_url="http://test",
        ) as client:
            resp = await client.post("/ahp/resolve", json={
                "approval_id": "ap-1",
                "decision": "invalid-value",
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_resolve_returns_502_when_ws_unavailable(self, gateway):
        """When resolve() returns False (WS down), endpoint should return 502."""
        client = AsyncMock()
        client.resolve = AsyncMock(return_value=False)
        app = create_http_app(gateway)
        add_resolve_endpoint(app, client)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post("/ahp/resolve", json={
                "approval_id": "ap-ws-down",
                "decision": "allow-once",
            })
        assert resp.status_code == 502
        assert "not delivered" in resp.json()["error"]

    @pytest.mark.asyncio
    async def test_resolve_requires_auth(self, gateway, mock_approval_client):
        """When auth is enabled, resolve requires a token."""
        original = os.environ.get("CS_AUTH_TOKEN")
        os.environ["CS_AUTH_TOKEN"] = "secret-token-for-resolve-test-1234"
        try:
            app = create_http_app(gateway)
            add_resolve_endpoint(app, mock_approval_client)
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                resp = await client.post("/ahp/resolve", json={
                    "approval_id": "ap-1", "decision": "deny",
                })
            assert resp.status_code == 401
        finally:
            if original is None:
                os.environ.pop("CS_AUTH_TOKEN", None)
            else:
                os.environ["CS_AUTH_TOKEN"] = original


class TestBuildOpenclawRuntimeEnforcement:
    """CS-010: _build_openclaw_runtime must forward enforcement fields."""

    def test_enforcement_fields_passed_to_config(self):
        runtime = _build_openclaw_runtime(
            webhook_token="tok",
            webhook_secret=None,
            webhook_require_https=False,
            webhook_max_body_bytes=1_000_000,
            source_protocol_version="1.0",
            git_short_sha="abc1234",
            profile_version=1,
            uds_path="/tmp/test.sock",
            gateway_host="127.0.0.1",
            gateway_port=8080,
            gateway_transport_preference="uds_first",
            enforcement_enabled=True,
            openclaw_ws_url="ws://127.0.0.1:19999",
            openclaw_operator_token="test-op-token",
        )
        assert runtime.config.enforcement_enabled is True
        assert runtime.config.openclaw_ws_url == "ws://127.0.0.1:19999"
        assert runtime.config.openclaw_operator_token == "test-op-token"
        assert runtime.approval_client._config.enabled is True
        assert runtime.approval_client._config.ws_url == "ws://127.0.0.1:19999"
        assert runtime.approval_client._config.operator_token == "test-op-token"

    def test_enforcement_defaults_when_omitted(self):
        runtime = _build_openclaw_runtime(
            webhook_token="tok",
            webhook_secret=None,
            webhook_require_https=False,
            webhook_max_body_bytes=1_000_000,
            source_protocol_version="1.0",
            git_short_sha="abc1234",
            profile_version=1,
            uds_path="/tmp/test.sock",
            gateway_host="127.0.0.1",
            gateway_port=8080,
            gateway_transport_preference="uds_first",
        )
        assert runtime.config.enforcement_enabled is False
        assert runtime.approval_client._config.enabled is False
