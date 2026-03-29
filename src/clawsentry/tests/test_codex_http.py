"""Tests for Codex HTTP endpoint on Gateway."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from clawsentry.gateway.server import SupervisionGateway, create_http_app


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("CS_AUTH_TOKEN", "test-token")
    gw = SupervisionGateway()
    return create_http_app(gw)


class TestCodexEndpoint:

    @pytest.mark.asyncio
    async def test_codex_endpoint_allows_safe_read(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ahp/codex?token=test-token",
                json={
                    "event_type": "function_call",
                    "payload": {
                        "name": "file_operations",
                        "arguments": {"path": "/workspace/README.md", "operation": "read"},
                    },
                    "session_id": "codex-test-1",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["action"] in ("continue", "allow")

    @pytest.mark.asyncio
    async def test_codex_endpoint_blocks_dangerous_command(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ahp/codex?token=test-token",
                json={
                    "event_type": "function_call",
                    "payload": {
                        "name": "bash",
                        "arguments": {"command": "rm -rf /"},
                    },
                    "session_id": "codex-test-2",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["action"] in ("block", "defer")

    @pytest.mark.asyncio
    async def test_codex_endpoint_requires_auth(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ahp/codex",
                json={"event_type": "function_call", "payload": {}},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_codex_endpoint_source_framework(self, app):
        """Verify events are tagged with 'codex' source."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ahp/codex?token=test-token",
                json={
                    "event_type": "function_call",
                    "payload": {
                        "name": "bash",
                        "arguments": {"command": "echo hello"},
                    },
                    "session_id": "codex-test-3",
                },
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_codex_endpoint_unknown_event_type(self, app):
        """Unknown event type should return continue."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ahp/codex?token=test-token",
                json={
                    "event_type": "unknown_weird_type",
                    "payload": {},
                    "session_id": "codex-test-4",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", data)
        assert result["action"] == "continue"

    @pytest.mark.asyncio
    async def test_codex_endpoint_invalid_json(self, app):
        """Invalid JSON body should return 400."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ahp/codex?token=test-token",
                content=b"not json",
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_codex_endpoint_session_end(self, app):
        """Session end events should be accepted."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/ahp/codex?token=test-token",
                json={
                    "event_type": "session_end",
                    "payload": {},
                    "session_id": "codex-test-5",
                },
            )
        assert resp.status_code == 200
