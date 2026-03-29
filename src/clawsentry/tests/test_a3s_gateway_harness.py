"""Tests for standard a3s-code gateway bridge harness (P1-2)."""

import asyncio
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


# ---------------------------------------------------------------------------
# E-9 Task 2: Dual-format auto-detection (JSON-RPC + native hook)
# ---------------------------------------------------------------------------


class TestNativeHookFormat:
    """Harness should accept raw hook JSON (no JSON-RPC wrapper)."""

    @pytest.fixture
    def harness(self):
        adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent.sock")
        return A3SGatewayHarness(adapter)

    @pytest.mark.asyncio
    async def test_native_pre_tool_use_detected(self, harness):
        """Native hook format without 'method' field should be auto-detected."""
        msg = {
            "event_type": "pre_tool_use",
            "payload": {
                "session_id": "sess-123",
                "tool": "Bash",
                "args": {"command": "echo hello"},
                "working_directory": "/workspace",
                "recent_tools": [],
            },
        }
        response = await harness.dispatch_async(msg)
        assert response is not None
        result = response.get("result", response)
        assert result["action"] in ("continue", "block", "defer", "modify")

    @pytest.mark.asyncio
    async def test_native_format_returns_simple_response(self, harness):
        """Native hook response should NOT have jsonrpc/id fields."""
        msg = {
            "event_type": "session_start",
            "payload": {"session_id": "sess-456"},
        }
        response = await harness.dispatch_async(msg)
        assert response is not None
        assert "jsonrpc" not in response

    @pytest.mark.asyncio
    async def test_jsonrpc_format_still_works(self, harness):
        """Existing JSON-RPC format should still work unchanged."""
        msg = {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "ahp/event",
            "params": {
                "event_type": "pre_tool_use",
                "payload": {"tool": "Bash", "command": "ls"},
            },
        }
        response = await harness.dispatch_async(msg)
        assert response is not None
        assert response.get("jsonrpc") == "2.0"
        assert response.get("id") == 42


class TestFrameworkArgument:
    """Harness --framework flag should set adapter source_framework."""

    def test_default_framework_is_a3s_code(self):
        adapter = A3SCodeAdapter()
        harness = A3SGatewayHarness(adapter)
        assert harness.adapter.source_framework == "a3s-code"

    def test_claude_code_framework(self):
        adapter = A3SCodeAdapter(source_framework="claude-code")
        harness = A3SGatewayHarness(adapter)
        assert harness.adapter.source_framework == "claude-code"


class TestCamelToSnake:
    """Test the _camel_to_snake helper."""

    def test_pre_tool_use(self):
        from clawsentry.adapters.a3s_gateway_harness import _camel_to_snake
        assert _camel_to_snake("PreToolUse") == "pre_tool_use"

    def test_post_tool_use(self):
        from clawsentry.adapters.a3s_gateway_harness import _camel_to_snake
        assert _camel_to_snake("PostToolUse") == "post_tool_use"

    def test_session_start(self):
        from clawsentry.adapters.a3s_gateway_harness import _camel_to_snake
        assert _camel_to_snake("SessionStart") == "session_start"

    def test_already_snake_case(self):
        from clawsentry.adapters.a3s_gateway_harness import _camel_to_snake
        assert _camel_to_snake("pre_tool_use") == "pre_tool_use"

    def test_generate_start(self):
        from clawsentry.adapters.a3s_gateway_harness import _camel_to_snake
        assert _camel_to_snake("GenerateStart") == "generate_start"


# ---------------------------------------------------------------------------
# E-9 Task 5: --async mode
# ---------------------------------------------------------------------------


class TestAsyncMode:
    """Harness --async flag should return immediately for non-blocking hooks."""

    @pytest.fixture
    def async_harness(self):
        adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent.sock")
        return A3SGatewayHarness(adapter, async_mode=True)

    @pytest.mark.asyncio
    async def test_async_mode_returns_continue_immediately(self, async_harness):
        msg = {
            "event_type": "post_tool_use",
            "payload": {"session_id": "s1", "tool": "Bash", "args": {}},
        }
        response = await async_harness.dispatch_async(msg)
        result = response.get("result", response)
        assert result["action"] == "continue"
        assert "async" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_async_mode_flag_default_false(self):
        adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent.sock")
        harness = A3SGatewayHarness(adapter)
        assert harness.async_mode is False

    @pytest.mark.asyncio
    async def test_async_jsonrpc_still_processed(self):
        """JSON-RPC messages should still be processed normally in async mode."""
        adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent.sock")
        harness = A3SGatewayHarness(adapter, async_mode=True)
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ahp/handshake",
            "params": {},
        }
        response = await harness.dispatch_async(msg)
        assert response is not None
        assert response.get("jsonrpc") == "2.0"


class TestAsyncBackgroundDispatch:
    """Async mode should dispatch to gateway in background, not drop."""

    @pytest.mark.asyncio
    async def test_async_mode_dispatches_in_background(self):
        adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent.sock")
        harness = A3SGatewayHarness(adapter, async_mode=True)

        msg = {
            "event_type": "post_tool_use",
            "payload": {"session_id": "s1", "tool": "Read", "args": {}},
        }

        from unittest.mock import AsyncMock, patch

        with patch.object(harness, "_handle_event", new_callable=AsyncMock) as mock_handle:
            result = await harness.dispatch_async(msg)
            # Should return immediately with continue
            assert result["result"]["action"] == "continue"
            # Background task should have been scheduled — let it run
            await asyncio.sleep(0.05)
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_mode_does_not_block_on_gateway_error(self):
        """Background dispatch errors should not propagate."""
        adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent.sock")
        harness = A3SGatewayHarness(adapter, async_mode=True)

        msg = {
            "event_type": "session_end",
            "payload": {"session_id": "s2"},
        }

        from unittest.mock import AsyncMock, patch

        with patch.object(
            harness, "_handle_event", new_callable=AsyncMock,
            side_effect=Exception("gateway down"),
        ):
            result = await harness.dispatch_async(msg)
            assert result["result"]["action"] == "continue"
            # Let the background task run (and fail silently)
            await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_async_reason_says_dispatched_not_queued(self):
        """Reason should say 'dispatched' not 'queued' (old behavior)."""
        adapter = A3SCodeAdapter(uds_path="/tmp/nonexistent.sock")
        harness = A3SGatewayHarness(adapter, async_mode=True)

        from unittest.mock import AsyncMock, patch

        msg = {
            "event_type": "post_tool_use",
            "payload": {"session_id": "s3", "tool": "Bash", "args": {}},
        }
        with patch.object(harness, "_handle_event", new_callable=AsyncMock):
            result = await harness.dispatch_async(msg)

        assert "dispatched" in result["result"]["reason"]
