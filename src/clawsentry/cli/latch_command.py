"""``clawsentry latch`` — install / start / stop / status for Latch integration."""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path


def run_latch_install() -> int:
    """Download and install the Latch binary."""
    from clawsentry.latch.binary_manager import (
        BinaryManager,
        ChecksumMismatchError,
        UnsupportedPlatformError,
    )

    mgr = BinaryManager()

    if mgr.is_installed:
        print(f"Latch binary already installed at {mgr.binary_path}")
        print("Use --force or uninstall first to reinstall.")
        return 0

    print("Downloading Latch binary...")
    try:
        path = mgr.install()
    except UnsupportedPlatformError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ChecksumMismatchError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return 1

    print(f"Latch installed: {path}")
    return 0


def run_latch_start(
    *,
    gateway_port: int = 8080,
    hub_port: int = 3006,
    no_browser: bool = False,
) -> int:
    """Start Gateway + Latch Hub full stack."""
    from clawsentry.latch.binary_manager import BinaryManager
    from clawsentry.latch.process_manager import ProcessManager, ServiceStatus

    mgr = BinaryManager()
    if not mgr.is_installed:
        print(
            "Latch binary not found. Run 'clawsentry latch install' first.",
            file=sys.stderr,
        )
        return 1

    pm = ProcessManager()

    # Check if already running
    if pm.gateway_status() == ServiceStatus.RUNNING:
        print("Gateway is already running.")
        return 1
    if pm.hub_status() == ServiceStatus.RUNNING:
        print("Latch Hub is already running.")
        return 1

    token = os.environ.get("CS_AUTH_TOKEN", "")
    gateway_url = f"http://127.0.0.1:{gateway_port}"
    hub_url = f"http://127.0.0.1:{hub_port}"

    print("Starting ClawSentry + Latch stack...")
    print(f"  Gateway:   {gateway_url}")
    print(f"  Latch Hub: {hub_url}")

    # 1. Start Gateway
    try:
        pm.start_gateway(port=gateway_port, extra_env={"CS_HTTP_PORT": str(gateway_port)})
    except RuntimeError as e:
        print(f"Failed to start Gateway: {e}", file=sys.stderr)
        return 1

    if not pm.wait_for_health(gateway_url, timeout=10.0):
        print("Gateway health check failed.", file=sys.stderr)
        pm.stop_all()
        return 1

    print("  Gateway: ready")

    # 2. Start Hub
    try:
        pm.start_hub(mgr.binary_path, port=hub_port, token=token)
    except RuntimeError as e:
        print(f"Failed to start Latch Hub: {e}", file=sys.stderr)
        pm.stop_all()
        return 1

    if not pm.wait_for_health(hub_url, timeout=10.0):
        print("Latch Hub health check failed.", file=sys.stderr)
        pm.stop_all()
        return 1

    print("  Latch Hub: ready")
    print()
    print("Stack is running. Use 'clawsentry latch stop' to shut down.")

    # 3. Open browser
    if not no_browser:
        ui_url = hub_url
        if token:
            ui_url += f"?token={token}"
        webbrowser.open(ui_url)

    return 0


def run_latch_stop() -> int:
    """Stop Gateway and Latch Hub."""
    from clawsentry.latch.process_manager import ProcessManager

    pm = ProcessManager()
    pm.stop_all()
    print("Stack stopped.")
    return 0


def run_latch_status() -> int:
    """Print status of Gateway and Latch Hub."""
    from clawsentry.latch.binary_manager import BinaryManager
    from clawsentry.latch.process_manager import ProcessManager

    mgr = BinaryManager()
    pm = ProcessManager()

    gw = pm.gateway_status()
    hub = pm.hub_status()

    print(f"Latch binary: {'installed' if mgr.is_installed else 'not installed'}")
    print(f"  Gateway:    {gw.value}", end="")
    gw_pid = pm._read_pid(pm.gateway_pid_file)
    if gw_pid is not None:
        print(f" (PID {gw_pid})", end="")
    print()

    print(f"  Latch Hub:  {hub.value}", end="")
    hub_pid = pm._read_pid(pm.hub_pid_file)
    if hub_pid is not None:
        print(f" (PID {hub_pid})", end="")
    print()

    return 0
