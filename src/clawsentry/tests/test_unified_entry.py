"""Tests for G-7: unified entry — gateway routes to stack, webhook conditional."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from clawsentry.adapters.openclaw_bootstrap import (
    DEFAULT_WEBHOOK_TOKEN,
    OpenClawBootstrapConfig,
)
from clawsentry.gateway.stack import _has_openclaw_config


# ---------------------------------------------------------------------------
# _has_openclaw_config detection
# ---------------------------------------------------------------------------
class TestHasOpenClawConfig:
    """_has_openclaw_config returns True only when user has explicitly
    configured OpenClaw environment variables."""

    def test_default_config_returns_false(self):
        cfg = OpenClawBootstrapConfig()
        assert _has_openclaw_config(cfg) is False

    def test_enforcement_enabled_returns_true(self):
        cfg = OpenClawBootstrapConfig(enforcement_enabled=True)
        assert _has_openclaw_config(cfg) is True

    def test_custom_webhook_token_returns_true(self):
        cfg = OpenClawBootstrapConfig(webhook_token="my-secret-token")
        assert _has_openclaw_config(cfg) is True

    def test_both_set_returns_true(self):
        cfg = OpenClawBootstrapConfig(
            enforcement_enabled=True,
            webhook_token="my-secret-token",
        )
        assert _has_openclaw_config(cfg) is True

    def test_default_token_enforcement_disabled_returns_false(self):
        cfg = OpenClawBootstrapConfig(
            webhook_token=DEFAULT_WEBHOOK_TOKEN,
            enforcement_enabled=False,
        )
        assert _has_openclaw_config(cfg) is False


# ---------------------------------------------------------------------------
# CLI routing: gateway -> stack.main, stack -> stack.main
# ---------------------------------------------------------------------------
class TestCLIRouting:
    """clawsentry gateway and clawsentry stack both route to stack.main."""

    def test_gateway_routes_to_stack_main(self, monkeypatch):
        mock_main = MagicMock()
        monkeypatch.setattr(
            "clawsentry.gateway.stack.main", mock_main,
        )
        import clawsentry.cli.main as cli_mod
        importlib.reload(cli_mod)

        with patch.object(cli_mod, "__name__", "__main__"):
            cli_mod.main(["gateway"])

        mock_main.assert_called_once()

    def test_stack_routes_to_stack_main(self, monkeypatch):
        mock_main = MagicMock()
        monkeypatch.setattr(
            "clawsentry.gateway.stack.main", mock_main,
        )
        import clawsentry.cli.main as cli_mod
        importlib.reload(cli_mod)

        with patch.object(cli_mod, "__name__", "__main__"):
            cli_mod.main(["stack"])

        mock_main.assert_called_once()

    def test_gateway_passes_remaining_args(self, monkeypatch):
        """Extra flags after 'gateway' are forwarded via sys.argv."""
        import sys
        captured_argv = []

        def mock_main():
            captured_argv.extend(sys.argv)

        monkeypatch.setattr(
            "clawsentry.gateway.stack.main", mock_main,
        )
        import clawsentry.cli.main as cli_mod
        importlib.reload(cli_mod)

        cli_mod.main(["gateway", "--gateway-port", "9999"])

        assert "--gateway-port" in captured_argv
        assert "9999" in captured_argv


# ---------------------------------------------------------------------------
# Updated help text
# ---------------------------------------------------------------------------
class TestUpdatedHelpText:
    """Gateway help text reflects auto-enable OpenClaw behavior."""

    def test_gateway_help_mentions_openclaw(self):
        import clawsentry.cli.main as cli_mod
        importlib.reload(cli_mod)
        parser = cli_mod._build_parser()
        help_output = parser.format_help()
        assert "OpenClaw" in help_output
