"""Tests for latch.process_manager."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from clawsentry.latch.process_manager import ProcessManager, ServiceStatus


# ---------------------------------------------------------------------------
# PID helpers
# ---------------------------------------------------------------------------


def test_write_and_read_pid(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    pm._write_pid(pm.gateway_pid_file, 12345)
    assert pm._read_pid(pm.gateway_pid_file) == 12345


def test_read_pid_missing(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    assert pm._read_pid(tmp_path / "nonexistent.pid") is None


def test_read_pid_corrupt(tmp_path: Path):
    f = tmp_path / "bad.pid"
    f.write_text("not-a-number")
    pm = ProcessManager(run_dir=tmp_path)
    assert pm._read_pid(f) is None


def test_remove_pid(tmp_path: Path):
    f = tmp_path / "test.pid"
    f.write_text("999")
    ProcessManager._remove_pid(f)
    assert not f.exists()


def test_remove_pid_missing(tmp_path: Path):
    """Removing non-existent PID file should not raise."""
    ProcessManager._remove_pid(tmp_path / "nope.pid")


# ---------------------------------------------------------------------------
# pid_alive
# ---------------------------------------------------------------------------


def test_pid_alive_current_process():
    assert ProcessManager._pid_alive(os.getpid()) is True


def test_pid_alive_nonexistent():
    # PID 99999999 is almost certainly not running
    assert ProcessManager._pid_alive(99999999) is False


# ---------------------------------------------------------------------------
# ServiceStatus
# ---------------------------------------------------------------------------


def test_gateway_status_stopped(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    assert pm.gateway_status() == ServiceStatus.STOPPED


def test_hub_status_stopped(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    assert pm.hub_status() == ServiceStatus.STOPPED


def test_gateway_status_running(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    pm._write_pid(pm.gateway_pid_file, os.getpid())
    assert pm.gateway_status() == ServiceStatus.RUNNING


def test_gateway_status_stale(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    pm._write_pid(pm.gateway_pid_file, 99999999)
    status = pm.gateway_status()
    assert status == ServiceStatus.STALE
    # PID file should be cleaned up
    assert not pm.gateway_pid_file.exists()


# ---------------------------------------------------------------------------
# start_gateway (mocked subprocess)
# ---------------------------------------------------------------------------


def test_start_gateway_success(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    mock_proc = mock.MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None  # process running
    mock_proc.pid = 42

    with mock.patch("subprocess.Popen", return_value=mock_proc), \
         mock.patch("time.sleep"):
        proc = pm.start_gateway(host="127.0.0.1", port=9999)

    assert proc.pid == 42
    assert pm._read_pid(pm.gateway_pid_file) == 42


def test_start_gateway_immediate_exit(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    mock_proc = mock.MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = 1  # exited immediately
    mock_proc.returncode = 1

    with mock.patch("subprocess.Popen", return_value=mock_proc), \
         mock.patch("time.sleep"):
        with pytest.raises(RuntimeError, match="Gateway exited immediately"):
            pm.start_gateway()


# ---------------------------------------------------------------------------
# start_hub (mocked subprocess)
# ---------------------------------------------------------------------------


def test_start_hub_success(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    latch_bin = tmp_path / "latch"
    latch_bin.write_text("#!/bin/sh\necho ok")

    mock_proc = mock.MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.pid = 99

    with mock.patch("subprocess.Popen", return_value=mock_proc), \
         mock.patch("time.sleep"):
        proc = pm.start_hub(latch_bin, port=3006, token="test-token")

    assert proc.pid == 99
    assert pm._read_pid(pm.hub_pid_file) == 99


def test_start_hub_immediate_exit(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    latch_bin = tmp_path / "latch"

    mock_proc = mock.MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = 1
    mock_proc.returncode = 1

    with mock.patch("subprocess.Popen", return_value=mock_proc), \
         mock.patch("time.sleep"):
        with pytest.raises(RuntimeError, match="Latch Hub exited immediately"):
            pm.start_hub(latch_bin)


# ---------------------------------------------------------------------------
# stop_all
# ---------------------------------------------------------------------------


def test_stop_all_no_processes(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    pm.stop_all()  # should not raise


def test_stop_all_with_running_pids(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    pm._write_pid(pm.gateway_pid_file, 12345)
    pm._write_pid(pm.hub_pid_file, 12346)

    with mock.patch.object(ProcessManager, "_pid_alive", return_value=False):
        pm.stop_all()

    assert not pm.gateway_pid_file.exists()
    assert not pm.hub_pid_file.exists()


def test_stop_all_sigterm_then_exits(tmp_path: Path):
    pm = ProcessManager(run_dir=tmp_path)
    pm._write_pid(pm.gateway_pid_file, 12345)

    # _pid_alive is called: 1st to decide if alive → True,
    # then in loop → True, then → False (process exited),
    # then final check after loop → False (already dead).
    # Use a function that starts True then switches to False after SIGTERM.
    call_count = 0

    def fake_alive(pid: int) -> bool:
        nonlocal call_count
        call_count += 1
        # First call: alive (triggers SIGTERM). Subsequent: dead.
        return call_count <= 1

    with mock.patch.object(
        ProcessManager, "_pid_alive", side_effect=fake_alive
    ), mock.patch("os.kill") as mock_kill, \
       mock.patch("time.sleep"):
        pm.stop_all(timeout=0.5)

    mock_kill.assert_called_once_with(12345, signal.SIGTERM)
    assert not pm.gateway_pid_file.exists()


# ---------------------------------------------------------------------------
# wait_for_health
# ---------------------------------------------------------------------------


def test_wait_for_health_success():
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = mock.MagicMock(return_value=False)

    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        assert ProcessManager.wait_for_health("http://localhost:8080") is True


def test_wait_for_health_timeout():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")), \
         mock.patch("time.sleep"):
        assert ProcessManager.wait_for_health(
            "http://localhost:8080", timeout=0.2, interval=0.05
        ) is False
