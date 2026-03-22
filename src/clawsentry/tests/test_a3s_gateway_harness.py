"""Tests for standard a3s-code gateway bridge harness (P1-2)."""

import os
import pytest
import pytest_asyncio
from clawsentry.adapters.a3s_adapter import A3SCodeAdapter
from clawsentry.gateway.server import SupervisionGateway, start_uds_server
from clawsentry.adapters.a3s_gateway_harness import A3SGatewayHarness


TEST_UDS_PATH = "/tmp/ahp-a3s-harness-test.sock"


@pytest_asyncio.fixture
async def harness_with_gateway():
    gw = SupervisionGateway()
    server = await start_uds_server(gw, TEST_UDS_PATH)
    adapter = A3SCodeAdapter(uds_path=TEST_UDS_PATH, default_deadline_ms=500)
    harness = A3SGatewayHarness(adapter=adapter)
    yield harness
    server.close()
    await server.wait_closed()
    if os.path.exists(TEST_UDS_PATH):
        os.unlink(TEST_UDS_PATH)


@pytest.mark.asyncio
async def test_handshake_returns_capabilities(harness_with_gateway):
    resp = await harness_with_gateway.dispatch_async(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ahp/handshake",
            "params": {"protocol_version": "2.0"},
        }
    )

    assert resp is not None
    assert resp["id"] == 1
    assert resp["result"]["protocol_version"] == "2.0"
    assert "pre_action" in resp["result"]["harness_info"]["capabilities"]


@pytest.mark.asyncio
async def test_pre_action_safe_command_allowed(harness_with_gateway):
    resp = await harness_with_gateway.dispatch_async(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "ahp/event",
            "params": {
                "event_type": "pre_action",
                "session_id": "sess-allow",
                "agent_id": "agent-allow",
                "payload": {
                    "tool": "read_file",
                    "arguments": {"path": "/tmp/x"},
                },
            },
        }
    )

    assert resp is not None
    result = resp["result"]
    assert result["decision"] == "allow"
    assert result["action"] == "continue"


@pytest.mark.asyncio
async def test_pre_action_dangerous_command_blocked(harness_with_gateway):
    resp = await harness_with_gateway.dispatch_async(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "ahp/event",
            "params": {
                "event_type": "pre_action",
                "session_id": "sess-block",
                "agent_id": "agent-block",
                "payload": {
                    "tool": "bash",
                    "arguments": {"command": "rm -rf /"},
                },
            },
        }
    )

    assert resp is not None
    result = resp["result"]
    assert result["decision"] == "block"
    assert result["action"] == "block"


@pytest.mark.asyncio
async def test_notification_post_action_returns_none(harness_with_gateway):
    resp = await harness_with_gateway.dispatch_async(
        {
            "jsonrpc": "2.0",
            "method": "ahp/event",
            "params": {
                "event_type": "post_action",
                "payload": {"tool": "bash", "result": {"success": True}},
            },
        }
    )
    assert resp is None


@pytest.mark.asyncio
async def test_unknown_event_type_returns_allow_result(harness_with_gateway):
    resp = await harness_with_gateway.dispatch_async(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "ahp/event",
            "params": {
                "event_type": "completely_unknown_event",
                "payload": {},
            },
        }
    )

    assert resp is not None
    result = resp["result"]
    assert result["decision"] == "allow"
    assert result["action"] == "continue"


@pytest.mark.asyncio
async def test_gateway_down_fallback_blocks_dangerous_pre_action():
    adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent-a3s-harness.sock")
    harness = A3SGatewayHarness(adapter=adapter)

    resp = await harness.dispatch_async(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "ahp/event",
            "params": {
                "event_type": "pre_action",
                "payload": {
                    "tool": "bash",
                    "arguments": {"command": "rm -rf /"},
                },
            },
        }
    )

    assert resp is not None
    result = resp["result"]
    assert result["decision"] == "block"
    assert result["action"] == "block"


@pytest.mark.asyncio
async def test_gateway_down_fallback_defers_safe_pre_action():
    adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent-a3s-harness.sock")
    harness = A3SGatewayHarness(adapter=adapter)

    resp = await harness.dispatch_async(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "ahp/event",
            "params": {
                "event_type": "pre_action",
                "payload": {
                    "tool": "read_file",
                    "arguments": {"path": "/tmp/x"},
                },
            },
        }
    )

    assert resp is not None
    result = resp["result"]
    assert result["decision"] == "defer"
    assert result["action"] == "defer"


# ---------------------------------------------------------------------------
# W-2: Error response must not leak exception details
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_error_does_not_leak_exception_detail():
    """W-2: Error responses must not expose raw exception messages."""
    from unittest.mock import AsyncMock, patch

    adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent-a3s-harness.sock")
    harness = A3SGatewayHarness(adapter=adapter)

    secret_message = "super secret internal traceback info 12345"

    with patch.object(
        harness,
        "_handle_event",
        new_callable=AsyncMock,
        side_effect=RuntimeError(secret_message),
    ):
        resp = await harness.dispatch_async(
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "ahp/event",
                "params": {
                    "event_type": "pre_action",
                    "payload": {"tool": "bash", "arguments": {"command": "ls"}},
                },
            }
        )

    assert resp is not None
    error = resp["error"]
    assert error["code"] == -32000
    assert secret_message not in error["message"]
    assert secret_message not in error["data"]["detail"]
    assert error["data"]["detail"] == "Internal harness error. Check server logs for details."
