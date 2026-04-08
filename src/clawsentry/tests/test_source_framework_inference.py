"""Tests for source_framework inference from caller_adapter (CS-024)."""

from __future__ import annotations

import pytest

from clawsentry.gateway.server import _infer_source_framework


class TestSourceFrameworkInference:
    """Infer missing/unknown source_framework from caller_adapter."""

    @pytest.mark.parametrize(
        ("source_framework", "caller_adapter", "expected"),
        [
            ("", "a3s-http", "a3s-code"),
            ("unknown", "a3s-http", "a3s-code"),
            ("", "a3s-uds", "a3s-code"),
            ("", "a3s-harness", "a3s-code"),
            ("", "a3s-adapter.v1", "a3s-code"),
            ("unknown", "a3s-http-adapter.v1", "a3s-code"),
            ("", "codex-http", "codex"),
            ("unknown", "openclaw", "openclaw"),
            ("", "claude-code", "claude-code"),
            ("", "unknown", "unknown"),
            ("", "", "unknown"),
        ],
    )
    def test_infers_from_adapter_when_missing_or_unknown(
        self,
        source_framework: str,
        caller_adapter: str,
        expected: str,
    ):
        assert _infer_source_framework(source_framework, caller_adapter) == expected

    def test_explicit_source_framework_preserved(self):
        assert _infer_source_framework("codex", "a3s-http") == "codex"
