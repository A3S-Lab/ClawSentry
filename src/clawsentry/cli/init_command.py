"""Handler for `clawsentry init <framework>`."""

from __future__ import annotations

import sys
from pathlib import Path

from .initializers import get_initializer


def run_init(
    *,
    framework: str,
    target_dir: Path,
    force: bool,
    auto_detect: bool = False,
    setup: bool = False,
    dry_run: bool = False,
    openclaw_home: Path | None = None,
) -> int:
    """Run init and print results. Returns exit code (0=ok, 1=error)."""
    # --setup implies --auto-detect
    if setup:
        auto_detect = True

    try:
        initializer = get_initializer(framework)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        kwargs: dict[str, object] = {"force": force}
        if auto_detect:
            kwargs["auto_detect"] = True
        if openclaw_home is not None:
            kwargs["openclaw_home"] = openclaw_home
        result = initializer.generate_config(target_dir, **kwargs)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"[clawsentry] {framework} integration initialized\n")

    if result.warnings:
        for w in result.warnings:
            print(f"  WARNING: {w}")
        print()

    print("  Files created:")
    for f in result.files_created:
        print(f"    {f}")
    print()

    print("  Environment variables:")
    for key, val in result.env_vars.items():
        print(f"    {key}={val}")
    print()

    print("  Next steps:")
    for i, step in enumerate(result.next_steps, 1):
        print(f"    {i}. {step}")
    print()

    # --- OpenClaw --setup ---
    if setup and hasattr(initializer, "setup_openclaw_config"):
        setup_kwargs: dict[str, object] = {"dry_run": dry_run}
        if openclaw_home is not None:
            setup_kwargs["openclaw_home"] = openclaw_home
        setup_result = initializer.setup_openclaw_config(**setup_kwargs)

        if setup_result.dry_run:
            print("  [DRY RUN] The following changes would be applied:")
        else:
            print("  OpenClaw configuration updated:")
        for change in setup_result.changes_applied:
            print(f"    - {change}")
        if setup_result.files_backed_up:
            print(
                f"  Backups: {', '.join(str(f) for f in setup_result.files_backed_up)}"
            )
        if setup_result.warnings:
            for w in setup_result.warnings:
                print(f"  WARNING: {w}")
        print()

    return 0
