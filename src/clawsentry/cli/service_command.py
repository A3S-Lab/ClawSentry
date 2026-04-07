"""``clawsentry service`` — install/uninstall platform service for auto-start.

Supports:
  - Linux: systemd user service (systemctl --user)
  - macOS: launchd user agent (~//Library/LaunchAgents)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path


def _which_clawsentry() -> str:
    """Find the absolute path to the clawsentry-gateway entry point."""
    # Prefer the entry point installed alongside this Python
    candidate = Path(sys.executable).parent / "clawsentry-gateway"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("clawsentry-gateway")
    if found:
        return found
    # Fallback to module invocation
    return f"{sys.executable} -m clawsentry.gateway.stack"


def _env_file_path() -> Path:
    config_dir = Path.home() / ".config" / "clawsentry"
    return config_dir / "gateway.env"


def _ensure_env_file() -> Path:
    """Create a template env file if it doesn't exist."""
    env_file = _env_file_path()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    if not env_file.exists():
        env_file.write_text(textwrap.dedent("""\
            # ClawSentry Gateway environment variables
            # See: https://elroyper.github.io/ClawSentry/operations/deployment/

            # Authentication token (required for production)
            # CS_AUTH_TOKEN=your-strong-random-token

            # LLM provider for L2/L3 (optional)
            # CS_LLM_PROVIDER=anthropic
            # ANTHROPIC_API_KEY=sk-ant-...

            # HTTP listen address
            # CS_HTTP_HOST=127.0.0.1
            # CS_HTTP_PORT=8080
        """), encoding="utf-8")
        os.chmod(str(env_file), 0o600)
    return env_file


# ---------------------------------------------------------------------------
# systemd (Linux)
# ---------------------------------------------------------------------------

_SYSTEMD_UNIT_NAME = "clawsentry-gateway.service"


def _systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _generate_systemd_unit(exec_start: str, env_file: Path) -> str:
    return textwrap.dedent(f"""\
        [Unit]
        Description=ClawSentry Supervision Gateway
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        ExecStart={exec_start}
        EnvironmentFile={env_file}
        Restart=on-failure
        RestartSec=5

        [Install]
        WantedBy=default.target
    """)


def _install_systemd(enable: bool = True) -> int:
    unit_dir = _systemd_user_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / _SYSTEMD_UNIT_NAME

    exec_start = _which_clawsentry()
    env_file = _ensure_env_file()
    unit_content = _generate_systemd_unit(exec_start, env_file)
    unit_path.write_text(unit_content, encoding="utf-8")
    print(f"  Wrote {unit_path}")
    print(f"  Env file: {env_file}")

    # Reload systemd
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print("  Reloaded systemd user daemon")

    if enable:
        subprocess.run(["systemctl", "--user", "enable", _SYSTEMD_UNIT_NAME], check=False)
        subprocess.run(["systemctl", "--user", "start", _SYSTEMD_UNIT_NAME], check=False)
        print(f"  Enabled and started {_SYSTEMD_UNIT_NAME}")
        print()
        print("  Useful commands:")
        print(f"    systemctl --user status {_SYSTEMD_UNIT_NAME}")
        print(f"    systemctl --user stop {_SYSTEMD_UNIT_NAME}")
        print(f"    journalctl --user -u {_SYSTEMD_UNIT_NAME} -f")
    else:
        print()
        print("  To enable and start:")
        print(f"    systemctl --user enable --now {_SYSTEMD_UNIT_NAME}")

    # Ensure lingering is enabled (services survive logout)
    user = os.getenv("USER", "")
    if user:
        result = subprocess.run(
            ["loginctl", "show-user", user, "--property=Linger"],
            capture_output=True, text=True,
        )
        if "Linger=no" in result.stdout:
            print()
            print("  NOTE: Enable lingering so the service runs after logout:")
            print(f"    sudo loginctl enable-linger {user}")

    return 0


def _uninstall_systemd() -> int:
    unit_path = _systemd_user_dir() / _SYSTEMD_UNIT_NAME
    if not unit_path.exists():
        print(f"  Service not installed ({unit_path} not found)")
        return 0

    subprocess.run(["systemctl", "--user", "stop", _SYSTEMD_UNIT_NAME], check=False)
    subprocess.run(["systemctl", "--user", "disable", _SYSTEMD_UNIT_NAME], check=False)
    unit_path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print(f"  Removed {unit_path}")
    print(f"  Stopped and disabled {_SYSTEMD_UNIT_NAME}")
    return 0


def _status_systemd() -> int:
    result = subprocess.run(
        ["systemctl", "--user", "status", _SYSTEMD_UNIT_NAME],
        capture_output=False,
    )
    return result.returncode


# ---------------------------------------------------------------------------
# launchd (macOS)
# ---------------------------------------------------------------------------

_LAUNCHD_LABEL = "com.clawsentry.gateway"


def _launchd_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _generate_launchd_plist(exec_path: str, env_file: Path) -> str:
    # Parse env file for ProgramArguments and EnvironmentVariables
    env_vars = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    env_dict_xml = ""
    if env_vars:
        entries = "\n".join(f"      <key>{k}</key>\n      <string>{v}</string>" for k, v in env_vars.items())
        env_dict_xml = f"    <key>EnvironmentVariables</key>\n    <dict>\n{entries}\n    </dict>"

    log_dir = Path.home() / ".local" / "log" / "clawsentry"

    parts = exec_path.split()
    args_xml = "\n".join(f"      <string>{p}</string>" for p in parts)

    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{_LAUNCHD_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
        {args_xml}
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>
        {env_dict_xml}
            <key>StandardOutPath</key>
            <string>{log_dir}/gateway.log</string>
            <key>StandardErrorPath</key>
            <string>{log_dir}/gateway.err</string>
        </dict>
        </plist>
    """)


def _install_launchd(enable: bool = True) -> int:
    plist_dir = _launchd_dir()
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"{_LAUNCHD_LABEL}.plist"

    exec_path = _which_clawsentry()
    env_file = _ensure_env_file()
    log_dir = Path.home() / ".local" / "log" / "clawsentry"
    log_dir.mkdir(parents=True, exist_ok=True)

    plist_content = _generate_launchd_plist(exec_path, env_file)
    plist_path.write_text(plist_content, encoding="utf-8")
    print(f"  Wrote {plist_path}")
    print(f"  Env file: {env_file}")
    print(f"  Logs: {log_dir}/")

    if enable:
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        print(f"  Loaded {_LAUNCHD_LABEL}")
        print()
        print("  Useful commands:")
        print(f"    launchctl list | grep clawsentry")
        print(f"    launchctl unload {plist_path}")
        print(f"    tail -f {log_dir}/gateway.log")

    return 0


def _uninstall_launchd() -> int:
    plist_path = _launchd_dir() / f"{_LAUNCHD_LABEL}.plist"
    if not plist_path.exists():
        print(f"  Service not installed ({plist_path} not found)")
        return 0

    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    plist_path.unlink()
    print(f"  Removed {plist_path}")
    print(f"  Unloaded {_LAUNCHD_LABEL}")
    return 0


def _status_launchd() -> int:
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True, text=True,
    )
    found = [line for line in result.stdout.splitlines() if "clawsentry" in line.lower()]
    if found:
        print("  ClawSentry launchd agent status:")
        for line in found:
            print(f"    {line}")
    else:
        print("  ClawSentry launchd agent not found. Install with: clawsentry service install")
    return 0 if found else 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_service_install(no_enable: bool = False) -> int:
    system = platform.system()
    print(f"\n  Installing ClawSentry service ({system})...")
    print()
    if system == "Linux":
        return _install_systemd(enable=not no_enable)
    elif system == "Darwin":
        return _install_launchd(enable=not no_enable)
    else:
        print(f"  Auto-start is not supported on {system}.")
        print("  Use 'clawsentry start --no-watch' to run in background.")
        return 1


def run_service_uninstall() -> int:
    system = platform.system()
    print(f"\n  Uninstalling ClawSentry service ({system})...")
    print()
    if system == "Linux":
        return _uninstall_systemd()
    elif system == "Darwin":
        return _uninstall_launchd()
    else:
        print(f"  No service to uninstall on {system}.")
        return 0


def run_service_status() -> int:
    system = platform.system()
    if system == "Linux":
        return _status_systemd()
    elif system == "Darwin":
        return _status_launchd()
    else:
        print(f"  Service management not supported on {system}.")
        return 1
