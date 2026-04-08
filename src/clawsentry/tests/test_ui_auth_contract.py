"""Static contract tests for auth bootstrap behavior in the React UI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "ui" / "src"


def test_app_bootstraps_query_token_before_auth_check() -> None:
    source = (ROOT / "App.tsx").read_text(encoding="utf-8")

    assert "bootstrapped" in source
    assert "setBootstrapped(true)" in source
    assert "if (!bootstrapped) return" in source
    assert "[bootstrapped, check]" in source
    assert "!bootstrapped || authenticated === null" in source
