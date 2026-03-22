"""Tests for Phase 5.1 — clawsentry init CLI."""

from __future__ import annotations

from pathlib import Path

from clawsentry.cli.initializers.base import InitResult


class TestInitResult:
    def test_init_result_fields(self):
        result = InitResult(
            files_created=[Path("/tmp/test")],
            env_vars={"KEY": "val"},
            next_steps=["step 1"],
            warnings=[],
        )
        assert result.files_created == [Path("/tmp/test")]
        assert result.env_vars == {"KEY": "val"}
        assert result.next_steps == ["step 1"]
        assert result.warnings == []

    def test_init_result_defaults_empty_warnings(self):
        result = InitResult(
            files_created=[],
            env_vars={},
            next_steps=[],
            warnings=[],
        )
        assert result.warnings == []


import pytest
from clawsentry.cli.initializers.openclaw import OpenClawInitializer


class TestOpenClawInitializer:
    def test_framework_name(self):
        init = OpenClawInitializer()
        assert init.framework_name == "openclaw"

    def test_generate_config_creates_env_file(self, tmp_path):
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        env_file = tmp_path / ".env.clawsentry"
        assert env_file.exists()
        assert env_file in result.files_created

    def test_generate_config_env_vars(self, tmp_path):
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        assert "OPENCLAW_WEBHOOK_TOKEN" in result.env_vars
        assert "CS_AUTH_TOKEN" in result.env_vars
        assert result.env_vars["CS_HTTP_PORT"] == "8080"
        assert result.env_vars["OPENCLAW_WEBHOOK_PORT"] == "8081"

    def test_generate_config_enforcement_env_vars(self, tmp_path):
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        assert result.env_vars["OPENCLAW_ENFORCEMENT_ENABLED"] == "false"
        assert result.env_vars["OPENCLAW_WS_URL"] == "ws://127.0.0.1:18789"
        assert "OPENCLAW_OPERATOR_TOKEN" in result.env_vars

    def test_generate_config_tokens_are_secure(self, tmp_path):
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        webhook_token = result.env_vars["OPENCLAW_WEBHOOK_TOKEN"]
        auth_token = result.env_vars["CS_AUTH_TOKEN"]
        assert len(webhook_token) >= 32
        assert len(auth_token) >= 32
        assert webhook_token != auth_token

    def test_generate_config_next_steps(self, tmp_path):
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        assert len(result.next_steps) >= 2
        assert any("source" in s for s in result.next_steps)
        assert any("stack" in s or "clawsentry stack" in s for s in result.next_steps)

    def test_generate_config_file_exists_no_force(self, tmp_path):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("existing")
        init = OpenClawInitializer()
        with pytest.raises(FileExistsError):
            init.generate_config(tmp_path, force=False)

    def test_generate_config_file_exists_force(self, tmp_path):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("existing")
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path, force=True)
        assert env_file in result.files_created
        assert len(result.warnings) >= 1

    def test_generate_config_env_file_content(self, tmp_path):
        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        content = (tmp_path / ".env.clawsentry").read_text()
        for key, val in result.env_vars.items():
            assert f"{key}={val}" in content


from clawsentry.cli.initializers.a3s_code import A3SCodeInitializer


class TestA3SCodeInitializer:
    def test_framework_name(self):
        init = A3SCodeInitializer()
        assert init.framework_name == "a3s-code"

    def test_generate_config_creates_env_file(self, tmp_path):
        init = A3SCodeInitializer()
        result = init.generate_config(tmp_path)
        env_file = tmp_path / ".env.clawsentry"
        assert env_file.exists()
        assert env_file in result.files_created

    def test_generate_config_env_vars(self, tmp_path):
        init = A3SCodeInitializer()
        result = init.generate_config(tmp_path)
        assert "CS_UDS_PATH" in result.env_vars
        assert "CS_AUTH_TOKEN" in result.env_vars
        assert result.env_vars["CS_UDS_PATH"] == "/tmp/clawsentry.sock"
        assert "OPENCLAW_WEBHOOK_TOKEN" not in result.env_vars

    def test_generate_config_token_is_secure(self, tmp_path):
        init = A3SCodeInitializer()
        result = init.generate_config(tmp_path)
        assert len(result.env_vars["CS_AUTH_TOKEN"]) >= 32

    def test_generate_config_next_steps(self, tmp_path):
        init = A3SCodeInitializer()
        result = init.generate_config(tmp_path)
        assert len(result.next_steps) >= 2
        assert any("source" in s for s in result.next_steps)
        assert any("gateway" in s for s in result.next_steps)

    def test_generate_config_file_exists_no_force(self, tmp_path):
        (tmp_path / ".env.clawsentry").write_text("existing")
        init = A3SCodeInitializer()
        with pytest.raises(FileExistsError):
            init.generate_config(tmp_path, force=False)

    def test_generate_config_file_exists_force(self, tmp_path):
        (tmp_path / ".env.clawsentry").write_text("existing")
        init = A3SCodeInitializer()
        result = init.generate_config(tmp_path, force=True)
        assert len(result.warnings) >= 1


from clawsentry.cli.initializers import FRAMEWORK_INITIALIZERS, get_initializer


class TestRegistry:
    def test_registry_has_both_frameworks(self):
        assert "openclaw" in FRAMEWORK_INITIALIZERS
        assert "a3s-code" in FRAMEWORK_INITIALIZERS

    def test_get_initializer_openclaw(self):
        init = get_initializer("openclaw")
        assert init.framework_name == "openclaw"

    def test_get_initializer_a3s_code(self):
        init = get_initializer("a3s-code")
        assert init.framework_name == "a3s-code"

    def test_get_initializer_unknown_raises(self):
        with pytest.raises(KeyError, match="unknown-fw"):
            get_initializer("unknown-fw")

    def test_registry_list(self):
        names = sorted(FRAMEWORK_INITIALIZERS.keys())
        assert names == ["a3s-code", "openclaw"]


from clawsentry.cli.init_command import run_init


class TestRunInit:
    def test_run_init_openclaw(self, tmp_path, capsys):
        exit_code = run_init(framework="openclaw", target_dir=tmp_path, force=False)
        assert exit_code == 0
        assert (tmp_path / ".env.clawsentry").exists()
        captured = capsys.readouterr()
        assert "openclaw" in captured.out.lower() or "OpenClaw" in captured.out

    def test_run_init_a3s_code(self, tmp_path, capsys):
        exit_code = run_init(framework="a3s-code", target_dir=tmp_path, force=False)
        assert exit_code == 0
        assert (tmp_path / ".env.clawsentry").exists()
        captured = capsys.readouterr()
        assert "a3s-code" in captured.out

    def test_run_init_unknown_framework(self, tmp_path, capsys):
        exit_code = run_init(framework="unknown", target_dir=tmp_path, force=False)
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "unknown" in captured.err.lower() or "Unknown" in captured.err

    def test_run_init_file_exists_returns_error(self, tmp_path, capsys):
        (tmp_path / ".env.clawsentry").write_text("existing")
        exit_code = run_init(framework="openclaw", target_dir=tmp_path, force=False)
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "exists" in captured.err.lower()

    def test_run_init_file_exists_force_succeeds(self, tmp_path, capsys):
        (tmp_path / ".env.clawsentry").write_text("existing")
        exit_code = run_init(framework="openclaw", target_dir=tmp_path, force=True)
        assert exit_code == 0

    def test_run_init_creates_target_dir(self, tmp_path, capsys):
        new_dir = tmp_path / "nonexistent" / "subdir"
        exit_code = run_init(framework="openclaw", target_dir=new_dir, force=False)
        assert exit_code == 0
        assert (new_dir / ".env.clawsentry").exists()


class TestInitOutputImprovement:
    """G-4: init output should include actionable guidance."""

    def test_openclaw_init_mentions_enforcement_extra(self, tmp_path):
        from clawsentry.cli.initializers.openclaw import OpenClawInitializer

        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        all_steps = "\n".join(result.next_steps)
        assert "enforcement" in all_steps.lower()

    def test_openclaw_init_mentions_openclaw_side_config(self, tmp_path):
        from clawsentry.cli.initializers.openclaw import OpenClawInitializer

        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        all_steps = "\n".join(result.next_steps)
        assert "tools" in all_steps and "exec" in all_steps and "host" in all_steps

    def test_openclaw_init_mentions_watch(self, tmp_path):
        from clawsentry.cli.initializers.openclaw import OpenClawInitializer

        init = OpenClawInitializer()
        result = init.generate_config(tmp_path)
        all_steps = "\n".join(result.next_steps)
        assert "watch" in all_steps

    def test_a3s_code_init_mentions_watch(self, tmp_path):
        from clawsentry.cli.initializers.a3s_code import A3SCodeInitializer

        init = A3SCodeInitializer()
        result = init.generate_config(tmp_path)
        all_steps = "\n".join(result.next_steps)
        assert "watch" in all_steps

    def test_a3s_code_init_mentions_http_port(self, tmp_path):
        from clawsentry.cli.initializers.a3s_code import A3SCodeInitializer

        init = A3SCodeInitializer()
        result = init.generate_config(tmp_path)
        all_steps = "\n".join(result.next_steps)
        assert "8080" in all_steps
