"""Tests for latch CLI commands (latch_command.py + main.py dispatch)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from clawsentry.latch.process_manager import ServiceStatus


# Helper: we need to patch the actual classes in the latch subpackage,
# then the deferred imports inside latch_command.py will pick them up.


def _run_install():
    """Import and call run_latch_install (forces fresh import each time)."""
    from clawsentry.cli.latch_command import run_latch_install
    return run_latch_install()


def _run_start(**kwargs):
    from clawsentry.cli.latch_command import run_latch_start
    return run_latch_start(**kwargs)


def _run_stop():
    from clawsentry.cli.latch_command import run_latch_stop
    return run_latch_stop()


def _run_status():
    from clawsentry.cli.latch_command import run_latch_status
    return run_latch_status()


# ---------------------------------------------------------------------------
# run_latch_install
# ---------------------------------------------------------------------------


def test_install_already_installed(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.binary_path",
        new_callable=mock.PropertyMock,
        return_value=Path("/fake/latch"),
    ):
        code = _run_install()

    assert code == 0
    assert "already installed" in capsys.readouterr().out


def test_install_success(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=False,
    ), mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.install",
        return_value=Path("/fake/latch"),
    ):
        code = _run_install()

    assert code == 0
    assert "installed" in capsys.readouterr().out.lower()


def test_install_unsupported_platform(capsys):
    from clawsentry.latch.binary_manager import UnsupportedPlatformError

    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=False,
    ), mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.install",
        side_effect=UnsupportedPlatformError("unsupported platform"),
    ):
        code = _run_install()

    assert code == 1
    assert "unsupported" in capsys.readouterr().err.lower()


def test_install_checksum_mismatch(capsys):
    from clawsentry.latch.binary_manager import ChecksumMismatchError

    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=False,
    ), mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.install",
        side_effect=ChecksumMismatchError("bad hash"),
    ):
        code = _run_install()

    assert code == 1


def test_install_download_error(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=False,
    ), mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.install",
        side_effect=OSError("network down"),
    ):
        code = _run_install()

    assert code == 1


# ---------------------------------------------------------------------------
# run_latch_start
# ---------------------------------------------------------------------------


def test_start_no_binary(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=False,
    ):
        code = _run_start(no_browser=True)

    assert code == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_start_gateway_already_running(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.RUNNING,
    ):
        code = _run_start(no_browser=True)

    assert code == 1
    assert "already running" in capsys.readouterr().out.lower()


def test_start_hub_already_running(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.hub_status",
        return_value=ServiceStatus.RUNNING,
    ):
        code = _run_start(no_browser=True)

    assert code == 1


def test_start_gateway_health_fails(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.hub_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.start_gateway",
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.wait_for_health",
        return_value=False,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.stop_all",
    ) as mock_stop:
        code = _run_start(no_browser=True)

    assert code == 1
    mock_stop.assert_called()


def test_start_success(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.binary_path",
        new_callable=mock.PropertyMock,
        return_value=Path("/fake/latch"),
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.hub_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.start_gateway",
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.start_hub",
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.wait_for_health",
        return_value=True,
    ), mock.patch.dict(os.environ, {"CS_AUTH_TOKEN": "test-tok"}):
        code = _run_start(no_browser=True)

    assert code == 0
    out = capsys.readouterr().out
    assert "ready" in out.lower()


def test_start_opens_browser():
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.binary_path",
        new_callable=mock.PropertyMock,
        return_value=Path("/fake/latch"),
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.hub_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.start_gateway",
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.start_hub",
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.wait_for_health",
        return_value=True,
    ), mock.patch("clawsentry.cli.latch_command.webbrowser") as mock_wb:
        code = _run_start(no_browser=False)

    assert code == 0
    mock_wb.open.assert_called_once()


def test_start_gateway_start_fails(capsys):
    """Gateway start raises RuntimeError."""
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.hub_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.start_gateway",
        side_effect=RuntimeError("exited immediately"),
    ):
        code = _run_start(no_browser=True)

    assert code == 1


# ---------------------------------------------------------------------------
# run_latch_stop
# ---------------------------------------------------------------------------


def test_stop(capsys):
    with mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.stop_all",
    ) as mock_stop:
        code = _run_stop()

    assert code == 0
    mock_stop.assert_called_once()
    assert "stopped" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# run_latch_status
# ---------------------------------------------------------------------------


def test_status_all_stopped(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=False,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.hub_status",
        return_value=ServiceStatus.STOPPED,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager._read_pid",
        return_value=None,
    ):
        code = _run_status()

    assert code == 0
    out = capsys.readouterr().out
    assert "not installed" in out


def test_status_running(capsys):
    with mock.patch(
        "clawsentry.latch.binary_manager.BinaryManager.is_installed",
        new_callable=mock.PropertyMock,
        return_value=True,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.gateway_status",
        return_value=ServiceStatus.RUNNING,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager.hub_status",
        return_value=ServiceStatus.RUNNING,
    ), mock.patch(
        "clawsentry.latch.process_manager.ProcessManager._read_pid",
        side_effect=[42, 99],
    ):
        code = _run_status()

    assert code == 0
    out = capsys.readouterr().out
    assert "installed" in out
    assert "running" in out
