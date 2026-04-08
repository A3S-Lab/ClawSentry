"""Helpers for probing whether a3s runtime consumes `.a3s-code/settings.json`."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class A3SSettingsProbeResult:
    verdict: str
    reason: str
    runtime_entrypoint: str
    request_count: int


def classify_settings_probe_result(
    *,
    runtime_entrypoint: str | None,
    request_count: int,
) -> A3SSettingsProbeResult:
    if not runtime_entrypoint:
        return A3SSettingsProbeResult(
            verdict="inconclusive",
            reason="runtime entrypoint not found on this machine",
            runtime_entrypoint="",
            request_count=request_count,
        )
    if request_count > 0:
        return A3SSettingsProbeResult(
            verdict="supported",
            reason="observed hook traffic from settings-based runtime path",
            runtime_entrypoint=runtime_entrypoint,
            request_count=request_count,
        )
    return A3SSettingsProbeResult(
        verdict="not_supported",
        reason="no hook traffic observed from settings-based runtime path",
        runtime_entrypoint=runtime_entrypoint,
        request_count=request_count,
    )
