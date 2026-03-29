"""Tests for Codex doctor checks."""

from __future__ import annotations

import pytest

from clawsentry.cli.doctor_command import check_codex_config


class TestDoctorCodexCheck:

    def test_codex_not_configured_skips(self, monkeypatch):
        monkeypatch.delenv("CS_FRAMEWORK", raising=False)
        result = check_codex_config()
        assert result.status == "PASS"
        assert "skipped" in result.message.lower()

    def test_codex_configured_with_token(self, monkeypatch):
        monkeypatch.setenv("CS_FRAMEWORK", "codex")
        monkeypatch.setenv("CS_AUTH_TOKEN", "a-strong-token-value")
        result = check_codex_config()
        assert result.status == "PASS"
        assert "/ahp/codex" in result.message

    def test_codex_configured_without_token(self, monkeypatch):
        monkeypatch.setenv("CS_FRAMEWORK", "codex")
        monkeypatch.delenv("CS_AUTH_TOKEN", raising=False)
        result = check_codex_config()
        assert result.status == "WARN"
        assert "CS_AUTH_TOKEN" in result.message

    def test_codex_custom_port(self, monkeypatch):
        monkeypatch.setenv("CS_FRAMEWORK", "codex")
        monkeypatch.setenv("CS_AUTH_TOKEN", "tok")
        monkeypatch.setenv("CS_HTTP_PORT", "9090")
        result = check_codex_config()
        assert result.status == "PASS"
        assert "9090" in result.message

    def test_codex_check_in_all_checks(self):
        from clawsentry.cli.doctor_command import ALL_CHECKS
        assert check_codex_config in ALL_CHECKS
