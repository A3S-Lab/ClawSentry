"""Latch Gateway + Hub process lifecycle management."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from enum import Enum
from pathlib import Path

from . import LATCH_DATA_DIR, LATCH_RUN_DIR


class ServiceStatus(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    STALE = "stale"


class ProcessManager:
    """Manage Gateway and Latch Hub processes via PID files."""

    def __init__(self, run_dir: Path | None = None) -> None:
        self._run_dir = run_dir or LATCH_RUN_DIR
        self._run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def gateway_pid_file(self) -> Path:
        return self._run_dir / "gateway.pid"

    @property
    def hub_pid_file(self) -> Path:
        return self._run_dir / "latch-hub.pid"

    # ------------------------------------------------------------------
    # PID file helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_pid(path: Path, pid: int) -> None:
        path.write_text(str(pid))

    @staticmethod
    def _read_pid(path: Path) -> int | None:
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _remove_pid(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    # ------------------------------------------------------------------
    # Start services
    # ------------------------------------------------------------------

    def start_gateway(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8080,
        log_path: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """Start ClawSentry Gateway as a background subprocess."""
        env = {**os.environ, **(extra_env or {})}
        effective_log = log_path or (self._run_dir / "gateway.log")
        effective_log.parent.mkdir(parents=True, exist_ok=True)

        with open(effective_log, "w") as log_fh:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "clawsentry.gateway.stack",
                    "--gateway-host", host,
                    "--gateway-port", str(port),
                ],
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env=env,
            )

        time.sleep(0.1)
        if proc.poll() is not None:
            raise RuntimeError(
                f"Gateway exited immediately with code {proc.returncode}"
            )

        self._write_pid(self.gateway_pid_file, proc.pid)
        return proc

    def start_hub(
        self,
        latch_binary: Path,
        *,
        port: int = 3006,
        token: str = "",
        data_dir: Path | None = None,
        log_path: Path | None = None,
    ) -> subprocess.Popen:
        """Start Latch Hub as a background subprocess."""
        effective_data = data_dir or LATCH_DATA_DIR
        effective_data.mkdir(parents=True, exist_ok=True)
        effective_log = log_path or (self._run_dir / "latch-hub.log")
        effective_log.parent.mkdir(parents=True, exist_ok=True)

        env = {
            **os.environ,
            "LATCH_HOME": str(effective_data),
            "LATCH_LISTEN_PORT": str(port),
        }
        if token:
            env["CLI_API_TOKEN"] = token

        with open(effective_log, "w") as log_fh:
            proc = subprocess.Popen(
                [str(latch_binary), "hub", "--no-relay", "--port", str(port)],
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env=env,
            )

        time.sleep(0.1)
        if proc.poll() is not None:
            raise RuntimeError(
                f"Latch Hub exited immediately with code {proc.returncode}"
            )

        self._write_pid(self.hub_pid_file, proc.pid)
        return proc

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def gateway_status(self) -> ServiceStatus:
        return self._check_status(self.gateway_pid_file)

    def hub_status(self) -> ServiceStatus:
        return self._check_status(self.hub_pid_file)

    def _check_status(self, pid_file: Path) -> ServiceStatus:
        pid = self._read_pid(pid_file)
        if pid is None:
            return ServiceStatus.STOPPED
        if self._pid_alive(pid):
            return ServiceStatus.RUNNING
        self._remove_pid(pid_file)
        return ServiceStatus.STALE

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    def stop_all(self, timeout: float = 5.0) -> None:
        """Stop both Gateway and Hub (SIGTERM → timeout → SIGKILL)."""
        for pid_file, name in [
            (self.hub_pid_file, "Latch Hub"),
            (self.gateway_pid_file, "Gateway"),
        ]:
            pid = self._read_pid(pid_file)
            if pid is None:
                continue
            if not self._pid_alive(pid):
                self._remove_pid(pid_file)
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline and self._pid_alive(pid):
                    time.sleep(0.1)
                if self._pid_alive(pid):
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            self._remove_pid(pid_file)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @staticmethod
    def wait_for_health(
        base_url: str,
        *,
        timeout: float = 5.0,
        interval: float = 0.1,
    ) -> bool:
        """Poll GET /health until 200 or timeout."""
        url = f"{base_url.rstrip('/')}/health"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1) as resp:
                    if resp.status == 200:
                        return True
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(interval)
        return False
