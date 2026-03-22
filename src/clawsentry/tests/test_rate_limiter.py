"""Tests for F-2: Rate limiter + ENGINE_UNAVAILABLE error code."""

import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from clawsentry.gateway.models import RPCErrorCode
from clawsentry.gateway.server import (
    SupervisionGateway,
    _RateLimiter,
    create_http_app,
)


# ---------------------------------------------------------------------------
# Unit tests for _RateLimiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_allows_under_limit(self):
        rl = _RateLimiter(max_requests=5, window_seconds=60.0)
        for _ in range(5):
            assert rl.check("client-1") is True

    def test_blocks_over_limit(self):
        rl = _RateLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            assert rl.check("client-1") is True
        assert rl.check("client-1") is False

    def test_window_expires(self):
        rl = _RateLimiter(max_requests=2, window_seconds=0.1)
        assert rl.check("client-1") is True
        assert rl.check("client-1") is True
        assert rl.check("client-1") is False
        # Wait for window to expire
        time.sleep(0.15)
        assert rl.check("client-1") is True

    def test_separate_clients(self):
        rl = _RateLimiter(max_requests=1, window_seconds=60.0)
        assert rl.check("client-1") is True
        assert rl.check("client-1") is False
        assert rl.check("client-2") is True  # Different client


# ---------------------------------------------------------------------------
# HTTP integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def gateway():
    return SupervisionGateway(trajectory_db_path=":memory:")


class TestRateLimitHTTP:
    @pytest.mark.asyncio
    async def test_rate_limited_http_response_429(self, monkeypatch, gateway):
        """POST /ahp returns 429 when rate limit exceeded."""
        monkeypatch.setenv("CS_RATE_LIMIT_PER_MINUTE", "2")
        monkeypatch.delenv("CS_AUTH_TOKEN", raising=False)
        app = create_http_app(gateway)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = json.dumps({
                "jsonrpc": "2.0", "method": "ahp/sync_decision", "id": 1,
                "params": {"request_id": "r1"},
            })
            # First 2 should pass (may return errors but not 429)
            for _ in range(2):
                resp = await client.post("/ahp", content=payload)
                assert resp.status_code != 429
            # Third should be rate limited
            resp = await client.post("/ahp", content=payload)
            assert resp.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limited_error_code(self, monkeypatch, gateway):
        """429 response contains RATE_LIMITED error code."""
        monkeypatch.setenv("CS_RATE_LIMIT_PER_MINUTE", "1")
        monkeypatch.delenv("CS_AUTH_TOKEN", raising=False)
        app = create_http_app(gateway)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = json.dumps({"jsonrpc": "2.0", "method": "ahp/sync_decision", "id": 1, "params": {}})
            await client.post("/ahp", content=payload)
            resp = await client.post("/ahp", content=payload)
            assert resp.status_code == 429
            body = resp.json()
            assert body["rpc_error_code"] == RPCErrorCode.RATE_LIMITED.value

    @pytest.mark.asyncio
    async def test_rate_limiter_disabled_when_zero(self, monkeypatch, gateway):
        """Rate limiter disabled when CS_RATE_LIMIT_PER_MINUTE=0."""
        monkeypatch.setenv("CS_RATE_LIMIT_PER_MINUTE", "0")
        monkeypatch.delenv("CS_AUTH_TOKEN", raising=False)
        app = create_http_app(gateway)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = json.dumps({"jsonrpc": "2.0", "method": "ahp/sync_decision", "id": 1, "params": {}})
            # Many requests should all pass (no 429)
            for _ in range(10):
                resp = await client.post("/ahp", content=payload)
                assert resp.status_code != 429

    @pytest.mark.asyncio
    async def test_rate_limited_a3s_endpoint(self, monkeypatch, gateway):
        """POST /ahp/a3s also respects rate limiting."""
        monkeypatch.setenv("CS_RATE_LIMIT_PER_MINUTE", "1")
        monkeypatch.delenv("CS_AUTH_TOKEN", raising=False)
        app = create_http_app(gateway)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"type": "handshake", "role": "hook"}
            await client.post("/ahp/a3s", json=payload)
            resp = await client.post("/ahp/a3s", json=payload)
            assert resp.status_code == 429


class TestEngineUnavailable:
    @pytest.mark.asyncio
    async def test_engine_unavailable_during_startup(self):
        """Gateway returns ENGINE_UNAVAILABLE when _ready is False."""
        gw = SupervisionGateway(trajectory_db_path=":memory:")
        gw._ready = False
        result = await gw.handle_jsonrpc(json.dumps({
            "jsonrpc": "2.0",
            "method": "ahp/sync_decision",
            "id": 1,
            "params": {"request_id": "r1"},
        }).encode())
        assert "error" in result
        data = result["error"].get("data", {})
        assert data.get("rpc_error_code") == RPCErrorCode.ENGINE_UNAVAILABLE.value

    @pytest.mark.asyncio
    async def test_engine_available_after_ready(self):
        """Gateway processes normally when _ready is True."""
        gw = SupervisionGateway(trajectory_db_path=":memory:")
        assert gw._ready is True
        result = await gw.handle_jsonrpc(json.dumps({
            "jsonrpc": "2.0",
            "method": "ahp/sync_decision",
            "id": 1,
            "params": {"request_id": "r1"},
        }).encode())
        # Should get a validation error (missing fields), not ENGINE_UNAVAILABLE
        if "error" in result:
            data = result["error"].get("data", {})
            assert data.get("rpc_error_code") != RPCErrorCode.ENGINE_UNAVAILABLE.value
