"""Tests for clawsentry start command."""

from __future__ import annotations

import json
from pathlib import Path

from clawsentry.cli.start_command import detect_framework


class TestDetectFramework:
    def test_detects_openclaw(self, tmp_path):
        oc_home = tmp_path / ".openclaw"
        oc_home.mkdir()
        (oc_home / "openclaw.json").write_text("{}")
        result = detect_framework(openclaw_home=oc_home)
        assert result == "openclaw"

    def test_detects_a3s_code(self, tmp_path):
        a3s_dir = tmp_path / ".a3s-code"
        a3s_dir.mkdir()
        result = detect_framework(openclaw_home=tmp_path / "nope", a3s_dir=a3s_dir)
        assert result == "a3s-code"

    def test_openclaw_takes_priority(self, tmp_path):
        oc_home = tmp_path / ".openclaw"
        oc_home.mkdir()
        (oc_home / "openclaw.json").write_text("{}")
        a3s_dir = tmp_path / ".a3s-code"
        a3s_dir.mkdir()
        result = detect_framework(openclaw_home=oc_home, a3s_dir=a3s_dir)
        assert result == "openclaw"

    def test_returns_none_when_nothing_found(self, tmp_path):
        result = detect_framework(
            openclaw_home=tmp_path / "nope",
            a3s_dir=tmp_path / "nope2",
        )
        assert result is None


class TestEnsureInit:
    def test_skips_init_when_env_exists(self, tmp_path):
        from clawsentry.cli.start_command import ensure_init

        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("CS_AUTH_TOKEN=existing-token\n")
        result = ensure_init(framework="openclaw", target_dir=tmp_path)
        assert result is False  # did NOT run init
        # File unchanged
        assert "existing-token" in env_file.read_text()

    def test_runs_init_when_env_missing(self, tmp_path):
        from clawsentry.cli.start_command import ensure_init

        result = ensure_init(framework="a3s-code", target_dir=tmp_path)
        assert result is True  # DID run init
        assert (tmp_path / ".env.clawsentry").exists()

    def test_runs_init_openclaw_with_auto_detect(self, tmp_path):
        from clawsentry.cli.start_command import ensure_init

        # Create fake openclaw config so auto-detect works
        oc_home = tmp_path / ".openclaw"
        oc_home.mkdir()
        (oc_home / "openclaw.json").write_text(json.dumps({
            "gateway": {"auth": {"token": "test-tok"}, "port": 18789},
            "tools": {"exec": {"host": "gateway"}},
        }))
        result = ensure_init(
            framework="openclaw",
            target_dir=tmp_path,
            openclaw_home=oc_home,
        )
        assert result is True
        env_content = (tmp_path / ".env.clawsentry").read_text()
        assert "OPENCLAW_OPERATOR_TOKEN=test-tok" in env_content

    def test_raises_runtime_error_on_init_failure(self, tmp_path):
        from unittest.mock import patch
        import pytest
        from clawsentry.cli.start_command import ensure_init

        with patch('clawsentry.cli.start_command.run_init', return_value=1):
            with pytest.raises(RuntimeError, match="Failed to initialize openclaw configuration"):
                ensure_init(framework="openclaw", target_dir=tmp_path)


import subprocess
import signal
import time
from unittest.mock import patch, MagicMock

from clawsentry.cli.start_command import (
    launch_gateway,
    wait_for_health,
    shutdown_gateway,
)


class TestLaunchGateway:
    def test_launch_returns_popen(self, tmp_path):
        log_file = tmp_path / "gateway.log"
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock(pid=12345)
            mock_proc.poll.return_value = None  # process still running
            mock_popen.return_value = mock_proc
            proc = launch_gateway(
                host="127.0.0.1",
                port=8080,
                log_path=log_file,
                extra_env={},
            )
            assert proc.pid == 12345
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            cmd = call_args[0][0]
            assert "clawsentry.gateway.stack" in " ".join(cmd)

    def test_raises_if_process_exits_immediately(self, tmp_path):
        log_file = tmp_path / "gateway.log"
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 1  # exited with error
            mock_proc.returncode = 1
            mock_popen.return_value = mock_proc
            import pytest
            with pytest.raises(RuntimeError, match="Gateway process exited immediately with code 1"):
                launch_gateway(
                    host="127.0.0.1",
                    port=8080,
                    log_path=log_file,
                    extra_env={},
                )


class TestWaitForHealth:
    def test_returns_true_when_healthy(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            assert wait_for_health("http://127.0.0.1:8080", timeout=1.0) is True

    def test_returns_false_on_timeout(self):
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            assert wait_for_health("http://127.0.0.1:8080", timeout=0.3) is False


class TestShutdownGateway:
    def test_terminates_process(self):
        proc = MagicMock()
        proc.poll.return_value = None  # still running
        proc.wait.return_value = 0
        shutdown_gateway(proc)
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    def test_kills_if_terminate_times_out(self):
        proc = MagicMock()
        proc.poll.return_value = None
        # First wait() times out, second wait() (after kill) succeeds
        proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="test", timeout=5),
            0,  # second wait() after kill succeeds
        ]
        shutdown_gateway(proc)
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_skips_shutdown_if_already_exited(self):
        proc = MagicMock()
        proc.poll.return_value = 0  # already exited
        shutdown_gateway(proc)
        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()


from clawsentry.cli.start_command import run_start


class TestRunStart:
    def test_run_start_banner_output(self, tmp_path, capsys):
        """Verify the startup banner prints correct info."""
        # Create .env.clawsentry so init is skipped
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("CS_AUTH_TOKEN=test-token-123\nCS_HTTP_PORT=8080\n")

        with (
            patch("clawsentry.cli.start_command.launch_gateway") as mock_launch,
            patch("clawsentry.cli.start_command.wait_for_health", return_value=True),
            patch("clawsentry.cli.start_command.run_watch_loop") as mock_watch,
            patch("clawsentry.cli.start_command.shutdown_gateway"),
        ):
            mock_launch.return_value = MagicMock(pid=99999)
            mock_watch.side_effect = KeyboardInterrupt  # simulate Ctrl+C

            run_start(
                framework="a3s-code",
                host="127.0.0.1",
                port=8080,
                target_dir=tmp_path,
                no_watch=False,
                interactive=False,
            )

            captured = capsys.readouterr()
            assert "ClawSentry starting" in captured.out
            assert "127.0.0.1:8080" in captured.out
            assert "test-token-123" in captured.out

    def test_run_start_no_watch_mode(self, tmp_path, capsys):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("CS_AUTH_TOKEN=abc\n")

        with (
            patch("clawsentry.cli.start_command.launch_gateway") as mock_launch,
            patch("clawsentry.cli.start_command.wait_for_health", return_value=True),
            patch("clawsentry.cli.start_command.run_watch_loop") as mock_watch,
            patch("clawsentry.cli.start_command.shutdown_gateway"),
        ):
            mock_launch.return_value = MagicMock(pid=99999)

            run_start(
                framework="a3s-code",
                host="127.0.0.1",
                port=8080,
                target_dir=tmp_path,
                no_watch=True,
                interactive=False,
            )

            mock_watch.assert_not_called()

    def test_run_start_exits_on_health_fail(self, tmp_path, capsys):
        env_file = tmp_path / ".env.clawsentry"
        env_file.write_text("CS_AUTH_TOKEN=abc\n")

        with (
            patch("clawsentry.cli.start_command.launch_gateway") as mock_launch,
            patch("clawsentry.cli.start_command.wait_for_health", return_value=False),
            patch("clawsentry.cli.start_command.shutdown_gateway") as mock_shutdown,
        ):
            mock_proc = MagicMock(pid=99999)
            mock_launch.return_value = mock_proc

            run_start(
                framework="a3s-code",
                host="127.0.0.1",
                port=8080,
                target_dir=tmp_path,
                no_watch=False,
                interactive=False,
            )

            captured = capsys.readouterr()
            assert "failed to start" in captured.err.lower() or "failed" in captured.out.lower()
            mock_shutdown.assert_called_once()
