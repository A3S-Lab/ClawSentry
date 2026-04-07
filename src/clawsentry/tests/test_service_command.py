"""Tests for ``clawsentry service`` command."""

from __future__ import annotations

import os
import platform
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from clawsentry.cli.service_command import (
    _which_clawsentry,
    _ensure_env_file,
    _generate_systemd_unit,
    _generate_launchd_plist,
    _env_file_path,
    run_service_install,
    run_service_uninstall,
    run_service_status,
)


# ---------------------------------------------------------------------------
# _which_clawsentry
# ---------------------------------------------------------------------------


class TestWhichClawsentry:
    def test_returns_string(self):
        result = _which_clawsentry()
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# _ensure_env_file
# ---------------------------------------------------------------------------


class TestEnsureEnvFile:
    def test_creates_env_file(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "clawsentry"
        monkeypatch.setattr(
            "clawsentry.cli.service_command._env_file_path",
            lambda: config_dir / "gateway.env",
        )
        env_file = _ensure_env_file()
        assert env_file.exists()
        content = env_file.read_text()
        assert "CS_AUTH_TOKEN" in content
        # Check permissions (owner-only)
        if platform.system() != "Windows":
            mode = oct(env_file.stat().st_mode & 0o777)
            assert mode == "0o600"

    def test_does_not_overwrite(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "clawsentry"
        config_dir.mkdir(parents=True)
        env_file = config_dir / "gateway.env"
        env_file.write_text("CUSTOM=value\n")
        monkeypatch.setattr(
            "clawsentry.cli.service_command._env_file_path",
            lambda: env_file,
        )
        result = _ensure_env_file()
        assert result.read_text() == "CUSTOM=value\n"


# ---------------------------------------------------------------------------
# _generate_systemd_unit
# ---------------------------------------------------------------------------


class TestGenerateSystemdUnit:
    def test_basic_unit(self, tmp_path):
        env_file = tmp_path / "gateway.env"
        env_file.touch()
        unit = _generate_systemd_unit("/usr/bin/clawsentry-gateway", env_file)
        assert "[Unit]" in unit
        assert "[Service]" in unit
        assert "[Install]" in unit
        assert "ExecStart=/usr/bin/clawsentry-gateway" in unit
        assert f"EnvironmentFile={env_file}" in unit
        assert "Restart=on-failure" in unit
        assert "WantedBy=default.target" in unit

    def test_module_invocation(self, tmp_path):
        env_file = tmp_path / "gateway.env"
        env_file.touch()
        unit = _generate_systemd_unit("/usr/bin/python -m clawsentry.gateway.stack", env_file)
        assert "ExecStart=/usr/bin/python -m clawsentry.gateway.stack" in unit


# ---------------------------------------------------------------------------
# _generate_launchd_plist
# ---------------------------------------------------------------------------


class TestGenerateLaunchdPlist:
    def test_basic_plist(self, tmp_path):
        env_file = tmp_path / "gateway.env"
        env_file.write_text("CS_AUTH_TOKEN=test123\n")
        plist = _generate_launchd_plist("/usr/local/bin/clawsentry-gateway", env_file)
        assert "com.clawsentry.gateway" in plist
        assert "<string>/usr/local/bin/clawsentry-gateway</string>" in plist
        assert "<key>RunAtLoad</key>" in plist
        assert "<key>KeepAlive</key>" in plist
        assert "CS_AUTH_TOKEN" in plist

    def test_empty_env_file(self, tmp_path):
        env_file = tmp_path / "gateway.env"
        env_file.write_text("# comments only\n")
        plist = _generate_launchd_plist("/usr/bin/test", env_file)
        assert "com.clawsentry.gateway" in plist

    def test_module_invocation_splits(self, tmp_path):
        env_file = tmp_path / "gateway.env"
        env_file.touch()
        plist = _generate_launchd_plist("/usr/bin/python -m clawsentry.gateway.stack", env_file)
        assert "<string>/usr/bin/python</string>" in plist
        assert "<string>-m</string>" in plist
        assert "<string>clawsentry.gateway.stack</string>" in plist


# ---------------------------------------------------------------------------
# run_service_install / uninstall / status (smoke tests)
# ---------------------------------------------------------------------------


class TestRunServiceInstall:
    @pytest.mark.skipif(platform.system() != "Linux", reason="Linux only")
    @patch("clawsentry.cli.service_command.subprocess.run")
    def test_install_linux(self, mock_run, tmp_path, monkeypatch):
        user_dir = tmp_path / ".config" / "systemd" / "user"
        monkeypatch.setattr(
            "clawsentry.cli.service_command._systemd_user_dir",
            lambda: user_dir,
        )
        monkeypatch.setattr(
            "clawsentry.cli.service_command._env_file_path",
            lambda: tmp_path / "gateway.env",
        )
        mock_run.return_value = MagicMock(returncode=0, stdout="Linger=yes")
        code = run_service_install(no_enable=True)
        assert code == 0
        unit_file = user_dir / "clawsentry-gateway.service"
        assert unit_file.exists()

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    @patch("clawsentry.cli.service_command.subprocess.run")
    def test_install_macos(self, mock_run, tmp_path, monkeypatch):
        agents_dir = tmp_path / "Library" / "LaunchAgents"
        monkeypatch.setattr(
            "clawsentry.cli.service_command._launchd_dir",
            lambda: agents_dir,
        )
        monkeypatch.setattr(
            "clawsentry.cli.service_command._env_file_path",
            lambda: tmp_path / "gateway.env",
        )
        log_dir = tmp_path / "log"
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mock_run.return_value = MagicMock(returncode=0)
        code = run_service_install(no_enable=True)
        assert code == 0

    @pytest.mark.skipif(platform.system() == "Windows", reason="Not Windows")
    @patch("clawsentry.cli.service_command.subprocess.run")
    def test_uninstall_no_service(self, mock_run, tmp_path, monkeypatch):
        if platform.system() == "Linux":
            monkeypatch.setattr(
                "clawsentry.cli.service_command._systemd_user_dir",
                lambda: tmp_path,
            )
        elif platform.system() == "Darwin":
            monkeypatch.setattr(
                "clawsentry.cli.service_command._launchd_dir",
                lambda: tmp_path,
            )
        code = run_service_uninstall()
        assert code == 0
