"""Tests for clawsentry watch CLI command."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest

from clawsentry.cli.watch_command import (
    format_alert,
    format_decision,
    format_event,
    handle_defer_interactive,
    parse_sse_line,
)


# ---------------------------------------------------------------------------
# TestParseSSELine
# ---------------------------------------------------------------------------


class TestParseSSELine:
    def test_data_line_returns_parsed_json(self):
        line = 'data: {"type": "decision", "risk_level": "high"}'
        result = parse_sse_line(line)
        assert result == {"type": "decision", "risk_level": "high"}

    def test_comment_line_returns_none(self):
        assert parse_sse_line(": keepalive") is None

    def test_empty_line_returns_none(self):
        assert parse_sse_line("") is None


# ---------------------------------------------------------------------------
# TestFormatDecision
# ---------------------------------------------------------------------------


class TestFormatDecision:
    def _make_decision(self, **overrides) -> dict:
        base = {
            "type": "decision",
            "session_id": "sess-001",
            "event_id": "evt-001",
            "risk_level": "high",
            "decision": "block",
            "command": "rm -rf /data",
            "reason": "D1: destructive pattern",
            "timestamp": "2026-03-22T10:30:45Z",
        }
        base.update(overrides)
        return base

    def test_block_decision_red_color(self):
        event = self._make_decision(decision="block", risk_level="high")
        result = format_decision(event, color=True)
        # Should contain ANSI red for BLOCK
        assert "\033[91m" in result
        assert "BLOCK" in result
        assert "rm -rf /data" in result
        assert "risk=high" in result
        assert "D1: destructive pattern" in result

    def test_allow_decision_green_color(self):
        event = self._make_decision(
            decision="allow", risk_level="low", command="echo hello"
        )
        result = format_decision(event, color=True)
        assert "\033[92m" in result
        assert "ALLOW" in result
        assert "echo hello" in result
        assert "risk=low" in result

    def test_defer_decision_no_color(self):
        event = self._make_decision(
            decision="defer", risk_level="medium", command="pip install requests"
        )
        result = format_decision(event, color=False)
        # No ANSI codes when color=False
        assert "\033[" not in result
        assert "DEFER" in result
        assert "pip install requests" in result
        assert "risk=medium" in result

    def test_command_truncated_to_40_chars(self):
        long_command = "a" * 60
        event = self._make_decision(command=long_command)
        result = format_decision(event, color=False)
        # The displayed command should be at most 40 chars (37 + "...")
        assert long_command not in result
        assert "aaa..." in result


# ---------------------------------------------------------------------------
# TestFormatAlert
# ---------------------------------------------------------------------------


class TestFormatAlert:
    def test_alert_formatting(self):
        event = {
            "type": "alert",
            "alert_id": "alert-abc123",
            "severity": "high",
            "session_id": "sess-001",
            "message": "Risk escalation detected",
            "timestamp": "2026-03-22T10:30:45Z",
        }
        result = format_alert(event, color=False)
        assert "ALERT" in result
        assert "sess=sess-001" in result
        assert "severity=high" in result
        assert "Risk escalation detected" in result

    def test_alert_with_color(self):
        event = {
            "type": "alert",
            "alert_id": "alert-abc123",
            "severity": "critical",
            "session_id": "sess-002",
            "message": "Critical risk",
            "timestamp": "2026-03-22T10:30:45Z",
        }
        result = format_alert(event, color=True)
        # Alert uses magenta
        assert "\033[95m" in result
        assert "ALERT" in result


# ---------------------------------------------------------------------------
# TestFormatEvent
# ---------------------------------------------------------------------------


class TestFormatEvent:
    def test_decision_dispatch(self):
        event = {
            "type": "decision",
            "decision": "block",
            "risk_level": "high",
            "command": "rm -rf /",
            "reason": "destructive",
            "timestamp": "2026-03-22T10:30:45Z",
        }
        result = format_event(event, color=False)
        assert "BLOCK" in result
        assert "rm -rf /" in result

    def test_alert_dispatch(self):
        event = {
            "type": "alert",
            "severity": "high",
            "session_id": "sess-001",
            "message": "Risk up",
            "timestamp": "2026-03-22T10:30:45Z",
        }
        result = format_event(event, color=False)
        assert "ALERT" in result

    def test_session_start_dispatch(self):
        event = {
            "type": "session_start",
            "session_id": "sess-abc",
            "agent_id": "agent-1",
            "source_framework": "openclaw",
            "timestamp": "2026-03-22T10:30:45Z",
        }
        result = format_event(event, color=False)
        assert "SESSION" in result
        assert "sess-abc" in result

    def test_json_mode_returns_json(self):
        event = {
            "type": "decision",
            "decision": "allow",
            "risk_level": "low",
            "command": "ls",
            "timestamp": "2026-03-22T10:30:45Z",
        }
        result = format_event(event, json_mode=True)
        parsed = json.loads(result)
        assert parsed["type"] == "decision"
        assert parsed["decision"] == "allow"


# ---------------------------------------------------------------------------
# TestWatchCLIParser
# ---------------------------------------------------------------------------


class TestWatchCLIParser:
    def test_watch_subcommand_exists(self):
        from clawsentry.cli.main import _build_parser

        parser = _build_parser()
        # Verify "watch" is a recognized subcommand by parsing it
        args, _ = parser.parse_known_args(["watch"])
        assert args.command == "watch"

    def test_watch_flags_parsed(self):
        from clawsentry.cli.main import _build_parser

        parser = _build_parser()
        args, _ = parser.parse_known_args([
            "watch",
            "--gateway-url", "http://localhost:9100",
            "--token", "secret123",
            "--filter", "decision,alert",
            "--json",
            "--no-color",
        ])
        assert args.command == "watch"
        assert args.gateway_url == "http://localhost:9100"
        assert args.token == "secret123"
        assert args.filter == "decision,alert"
        assert args.json is True
        assert args.no_color is True

    def test_interactive_flag_parsed(self):
        from clawsentry.cli.main import _build_parser

        parser = _build_parser()
        args, _ = parser.parse_known_args(["watch", "--interactive"])
        assert args.interactive is True

    def test_interactive_short_flag_parsed(self):
        from clawsentry.cli.main import _build_parser

        parser = _build_parser()
        args, _ = parser.parse_known_args(["watch", "-i"])
        assert args.interactive is True


# ---------------------------------------------------------------------------
# TestInteractivePrompt
# ---------------------------------------------------------------------------


class TestInteractivePrompt:
    """Tests for handle_defer_interactive()."""

    def _make_defer_event(self, **overrides) -> dict:
        """Build a DEFER decision event with sensible defaults."""
        # expires_at is in milliseconds (30 seconds from now)
        base = {
            "type": "decision",
            "decision": "defer",
            "risk_level": "medium",
            "command": "pip install requests",
            "reason": "D3: network access",
            "approval_id": "appr-abc-123",
            "expires_at": int((time.time() + 30) * 1000),
            "timestamp": "2026-03-22T10:30:45Z",
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    async def test_handle_defer_allow(self):
        """User inputs 'a' -> resolve called with allow-once, returns 'allow'."""
        resolve_fn = AsyncMock(return_value=True)
        event = self._make_defer_event()

        result = await handle_defer_interactive(
            event,
            resolve_fn=resolve_fn,
            _input_fn=lambda _prompt: "a",
        )

        assert result == "allow"
        resolve_fn.assert_called_once_with(
            event["approval_id"], "allow-once",
        )

    @pytest.mark.asyncio
    async def test_handle_defer_deny(self):
        """User inputs 'd' -> resolve called with deny + reason, returns 'deny'."""
        resolve_fn = AsyncMock(return_value=True)
        event = self._make_defer_event()

        result = await handle_defer_interactive(
            event,
            resolve_fn=resolve_fn,
            _input_fn=lambda _prompt: "d",
        )

        assert result == "deny"
        resolve_fn.assert_called_once()
        call_args = resolve_fn.call_args
        assert call_args[0][0] == event["approval_id"]
        assert call_args[0][1] == "deny"
        assert "operator denied" in call_args[1]["reason"]

    @pytest.mark.asyncio
    async def test_handle_defer_skip(self):
        """User inputs 's' -> resolve NOT called, returns 'skip'."""
        resolve_fn = AsyncMock(return_value=True)
        event = self._make_defer_event()

        result = await handle_defer_interactive(
            event,
            resolve_fn=resolve_fn,
            _input_fn=lambda _prompt: "s",
        )

        assert result == "skip"
        resolve_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_defer_expired_skips(self):
        """expires_at in the past -> returns 'expired' without prompting."""
        resolve_fn = AsyncMock(return_value=True)
        # Set expires_at to 1 second ago (well within SAFETY_MARGIN_S)
        event = self._make_defer_event(
            expires_at=int((time.time() - 1) * 1000),
        )
        called = False

        def _should_not_be_called(_prompt):
            nonlocal called
            called = True
            return "a"

        result = await handle_defer_interactive(
            event,
            resolve_fn=resolve_fn,
            _input_fn=_should_not_be_called,
        )

        assert result == "expired"
        assert not called, "_input_fn should not have been called"
        resolve_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_defer_no_approval_id_skips(self):
        """No approval_id -> returns 'skip' without prompting."""
        resolve_fn = AsyncMock(return_value=True)
        event = self._make_defer_event(approval_id=None)
        called = False

        def _should_not_be_called(_prompt):
            nonlocal called
            called = True
            return "a"

        result = await handle_defer_interactive(
            event,
            resolve_fn=resolve_fn,
            _input_fn=_should_not_be_called,
        )

        assert result == "skip"
        assert not called, "_input_fn should not have been called"
        resolve_fn.assert_not_called()
