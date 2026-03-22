"""Tests for stack startup config validation (G-3)."""

import pytest

from clawsentry.gateway.stack import validate_stack_config


class TestStackConfigValidation:

    def test_enforcement_enabled_without_token_raises(self):
        with pytest.raises(SystemExit) as exc_info:
            validate_stack_config(
                enforcement_enabled=True,
                operator_token="",
                ws_url="ws://127.0.0.1:18789",
            )
        assert exc_info.value.code != 0

    def test_enforcement_enabled_with_token_passes(self):
        validate_stack_config(
            enforcement_enabled=True,
            operator_token="valid-token-here",
            ws_url="ws://127.0.0.1:18789",
        )

    def test_enforcement_disabled_ignores_empty_token(self):
        validate_stack_config(
            enforcement_enabled=False,
            operator_token="",
            ws_url="ws://127.0.0.1:18789",
        )

    def test_invalid_ws_url_scheme_raises(self):
        with pytest.raises(SystemExit):
            validate_stack_config(
                enforcement_enabled=True,
                operator_token="valid-token",
                ws_url="http://127.0.0.1:18789",
            )

    def test_enforcement_enabled_without_ws_url_raises(self):
        with pytest.raises(SystemExit):
            validate_stack_config(
                enforcement_enabled=True,
                operator_token="valid-token",
                ws_url="",
            )

    def test_enforcement_disabled_ignores_empty_ws_url(self):
        """When enforcement is disabled, empty ws_url should not cause errors."""
        validate_stack_config(
            enforcement_enabled=False,
            operator_token="",
            ws_url="",
        )

    def test_enforcement_disabled_ignores_invalid_ws_url(self):
        """When enforcement is disabled, invalid ws_url scheme should not cause errors."""
        validate_stack_config(
            enforcement_enabled=False,
            operator_token="",
            ws_url="http://bad-scheme",
        )

    def test_wss_scheme_accepted(self):
        """wss:// scheme should be accepted for secure WebSocket connections."""
        validate_stack_config(
            enforcement_enabled=True,
            operator_token="valid-token",
            ws_url="wss://secure.example.com:18789",
        )

    def test_multiple_errors_reported(self, capsys):
        """When both token and ws_url are invalid, both errors should be reported."""
        with pytest.raises(SystemExit):
            validate_stack_config(
                enforcement_enabled=True,
                operator_token="",
                ws_url="",
            )
        captured = capsys.readouterr()
        # Both errors should appear in stderr
        assert "OPENCLAW_OPERATOR_TOKEN" in captured.err
        assert "OPENCLAW_WS_URL" in captured.err
