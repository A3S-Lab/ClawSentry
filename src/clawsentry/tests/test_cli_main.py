"""Tests for unified CLI entry point."""

from __future__ import annotations

import importlib
import subprocess
import sys


class TestCLIParsing:
    def test_no_args_shows_help(self):
        proc = subprocess.run(
            [sys.executable, "-m", "clawsentry", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        assert "init" in proc.stdout
        assert "gateway" in proc.stdout

    def test_init_subcommand_help(self):
        proc = subprocess.run(
            [sys.executable, "-m", "clawsentry", "init", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        assert "framework" in proc.stdout.lower()

    def test_init_unknown_framework(self):
        proc = subprocess.run(
            [sys.executable, "-m", "clawsentry", "init", "nonexistent"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode != 0

    def test_init_openclaw_in_tmpdir(self, tmp_path):
        proc = subprocess.run(
            [
                sys.executable, "-m", "clawsentry",
                "init", "openclaw", "--dir", str(tmp_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        assert (tmp_path / ".env.clawsentry").exists()

    def test_init_a3s_code_in_tmpdir(self, tmp_path):
        proc = subprocess.run(
            [
                sys.executable, "-m", "clawsentry",
                "init", "a3s-code", "--dir", str(tmp_path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        assert (tmp_path / ".env.clawsentry").exists()


class TestWatchDefaults:
    """G-1: watch default URL must align with gateway default port."""

    def test_watch_default_url_matches_gateway_port(self):
        """Without env override, watch should default to port 8080."""
        # Re-import to ensure fresh module state
        import clawsentry.cli.main as cli_mod
        importlib.reload(cli_mod)
        parser = cli_mod._build_parser()
        args, _ = parser.parse_known_args(["watch"])
        assert "8080" in args.gateway_url

    def test_watch_default_url_reads_env(self, monkeypatch):
        """CS_HTTP_PORT env var should override the default port in watch."""
        monkeypatch.setenv("CS_HTTP_PORT", "9999")
        # Must reload so the env var is picked up at parser construction time
        import clawsentry.cli.main as cli_mod
        importlib.reload(cli_mod)
        parser = cli_mod._build_parser()
        args, _ = parser.parse_known_args(["watch"])
        assert "9999" in args.gateway_url
