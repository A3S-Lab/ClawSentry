"""Base protocol and data structures for framework initializers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class InitResult:
    """Result of a framework initialization."""

    files_created: list[Path]
    env_vars: dict[str, str]
    next_steps: list[str]
    warnings: list[str]


@dataclass
class SetupResult:
    """Result of an OpenClaw setup operation (--setup)."""

    changes_applied: list[str]
    files_modified: list[Path]
    files_backed_up: list[Path]
    warnings: list[str]
    dry_run: bool


ENV_FILE_NAME = ".env.clawsentry"


class FrameworkInitializer(Protocol):
    """Protocol for framework-specific initializers."""

    framework_name: str

    def generate_config(
        self, target_dir: Path, *, force: bool = False
    ) -> InitResult: ...
