"""Tests for init openclaw --auto-detect (G-5)."""

import json
from pathlib import Path

import pytest

from clawsentry.cli.initializers.openclaw import OpenClawInitializer


class TestOpenClawAutoDetect:

    def _write_openclaw_config(self, dir_path: Path, config: dict) -> Path:
        openclaw_dir = dir_path / ".openclaw"
        openclaw_dir.mkdir(parents=True, exist_ok=True)
        config_file = openclaw_dir / "openclaw.json"
        config_file.write_text(json.dumps(config))
        return config_file

    def test_auto_detect_extracts_token(self, tmp_path):
        self._write_openclaw_config(tmp_path, {
            "gateway": {"auth": {"token": "my-secret-token-123"}}
        })
        init = OpenClawInitializer()
        result = init.generate_config(
            tmp_path, auto_detect=True,
            openclaw_home=tmp_path / ".openclaw",
        )
        assert result.env_vars["OPENCLAW_OPERATOR_TOKEN"] == "my-secret-token-123"

    def test_auto_detect_extracts_port(self, tmp_path):
        self._write_openclaw_config(tmp_path, {
            "gateway": {
                "auth": {"token": "tok"},
                "port": 19000,
            }
        })
        init = OpenClawInitializer()
        result = init.generate_config(
            tmp_path, auto_detect=True,
            openclaw_home=tmp_path / ".openclaw",
        )
        assert "19000" in result.env_vars["OPENCLAW_WS_URL"]

    def test_auto_detect_warns_missing_exec_host(self, tmp_path):
        self._write_openclaw_config(tmp_path, {
            "gateway": {"auth": {"token": "tok"}},
        })
        init = OpenClawInitializer()
        result = init.generate_config(
            tmp_path, auto_detect=True,
            openclaw_home=tmp_path / ".openclaw",
        )
        warnings_text = "\n".join(result.warnings)
        assert "tools" in warnings_text.lower() or "exec" in warnings_text.lower() or "host" in warnings_text.lower()

    def test_auto_detect_no_warning_when_exec_host_correct(self, tmp_path):
        self._write_openclaw_config(tmp_path, {
            "gateway": {"auth": {"token": "tok"}},
            "tools": {"exec": {"host": "gateway"}},
        })
        init = OpenClawInitializer()
        result = init.generate_config(
            tmp_path, auto_detect=True,
            openclaw_home=tmp_path / ".openclaw",
        )
        # Should have no warning about tools.exec.host
        warnings_text = "\n".join(result.warnings)
        assert "tools.exec.host" not in warnings_text

    def test_auto_detect_sets_enforcement_enabled(self, tmp_path):
        self._write_openclaw_config(tmp_path, {
            "gateway": {"auth": {"token": "tok"}},
        })
        init = OpenClawInitializer()
        result = init.generate_config(
            tmp_path, auto_detect=True,
            openclaw_home=tmp_path / ".openclaw",
        )
        assert result.env_vars["OPENCLAW_ENFORCEMENT_ENABLED"] == "true"

    def test_auto_detect_missing_openclaw_dir(self, tmp_path):
        init = OpenClawInitializer()
        result = init.generate_config(
            tmp_path, auto_detect=True,
            openclaw_home=tmp_path / ".openclaw",
        )
        assert result.env_vars["OPENCLAW_OPERATOR_TOKEN"] == ""
        warnings_text = "\n".join(result.warnings)
        assert len(result.warnings) > 0  # Should have at least one warning

    def test_without_auto_detect_uses_defaults(self, tmp_path):
        self._write_openclaw_config(tmp_path, {
            "gateway": {"auth": {"token": "tok"}},
        })
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)  # no auto_detect
        assert result.env_vars["OPENCLAW_OPERATOR_TOKEN"] == ""
        assert result.env_vars["OPENCLAW_ENFORCEMENT_ENABLED"] == "false"
