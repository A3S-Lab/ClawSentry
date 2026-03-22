"""a3s-code framework initializer."""

from __future__ import annotations

import secrets
from pathlib import Path

from .base import ENV_FILE_NAME, InitResult


class A3SCodeInitializer:
    """Generate configuration for a3s-code integration."""

    framework_name: str = "a3s-code"

    def generate_config(
        self, target_dir: Path, *, force: bool = False, **_kwargs: object
    ) -> InitResult:
        env_path = target_dir / ENV_FILE_NAME
        warnings: list[str] = []

        if env_path.exists() and not force:
            raise FileExistsError(
                f"{env_path} already exists. Use --force to overwrite."
            )
        if env_path.exists() and force:
            warnings.append(f"Overwriting existing {env_path}")

        env_vars = {
            "CS_UDS_PATH": "/tmp/clawsentry.sock",
            "CS_AUTH_TOKEN": secrets.token_urlsafe(32),
        }

        lines = ["# ClawSentry — a3s-code integration config"]
        for key, val in env_vars.items():
            lines.append(f"{key}={val}")
        lines.append("")
        env_path.write_text("\n".join(lines))
        env_path.chmod(0o600)  # tokens are sensitive

        next_steps = [
            f"source {ENV_FILE_NAME}",
            "clawsentry gateway    # starts on UDS + HTTP port 8080",
            (
                "Configure a3s-code AHP transport:\n"
                '  program: "clawsentry-harness"'
            ),
            "clawsentry watch    # real-time terminal monitoring (port 8080)",
        ]

        return InitResult(
            files_created=[env_path],
            env_vars=env_vars,
            next_steps=next_steps,
            warnings=warnings,
        )
