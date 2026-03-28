"""Tests for E-8 D4 Tool Frequency Anomaly Detection.

Covers:
- Burst detection (~6 tests)
- Repetitive detection (~5 tests)
- Rate detection (~4 tests)
- Combined logic (~5 tests)
- Config (~3 tests)
- Memory/reset (~2 tests)
"""

from __future__ import annotations

import pytest

from clawsentry.gateway.detection_config import (
    DetectionConfig,
    build_detection_config_from_env,
)
from clawsentry.gateway.risk_snapshot import SessionRiskTracker


# ---------------------------------------------------------------------------
# Burst detection
# ---------------------------------------------------------------------------


class TestBurstDetection:
    """Burst: same tool >= 10 times in 5 seconds → d4=2."""

    def test_no_calls_d4_zero(self) -> None:
        t = SessionRiskTracker()
        assert t.get_d4("sess-1") == 0

    def test_below_burst_threshold(self) -> None:
        t = SessionRiskTracker(freq_burst_count=10, freq_burst_window_s=5.0)
        now = 1000.0
        for i in range(9):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        assert t._get_frequency_d4("sess-1", now=now + 1.0) == 0

    def test_at_burst_threshold(self) -> None:
        t = SessionRiskTracker(freq_burst_count=10, freq_burst_window_s=5.0)
        now = 1000.0
        for i in range(10):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        assert t._get_frequency_d4("sess-1", now=now + 1.0) == 2

    def test_burst_different_tools_no_trigger(self) -> None:
        t = SessionRiskTracker(freq_burst_count=10, freq_burst_window_s=5.0)
        now = 1000.0
        for i in range(10):
            t.record_tool_call("sess-1", f"tool_{i}", now=now + i * 0.1)
        assert t._get_frequency_d4("sess-1", now=now + 1.0) == 0

    def test_burst_outside_window(self) -> None:
        t = SessionRiskTracker(freq_burst_count=10, freq_burst_window_s=5.0)
        now = 1000.0
        for i in range(10):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        # Check well after burst window expires
        assert t._get_frequency_d4("sess-1", now=now + 10.0) == 0

    def test_burst_different_sessions(self) -> None:
        t = SessionRiskTracker(freq_burst_count=10, freq_burst_window_s=5.0)
        now = 1000.0
        for i in range(5):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        for i in range(5):
            t.record_tool_call("sess-2", "bash", now=now + i * 0.1)
        assert t._get_frequency_d4("sess-1", now=now + 1.0) == 0
        assert t._get_frequency_d4("sess-2", now=now + 1.0) == 0


# ---------------------------------------------------------------------------
# Repetitive detection
# ---------------------------------------------------------------------------


class TestRepetitiveDetection:
    """Repetitive: same tool >= 20 times in 60 seconds → d4=1."""

    def test_below_repetitive_threshold(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=100,  # disable burst for this test
            freq_repetitive_count=20,
            freq_repetitive_window_s=60.0,
        )
        now = 1000.0
        for i in range(19):
            t.record_tool_call("sess-1", "read_file", now=now + i * 2.0)
        assert t._get_frequency_d4("sess-1", now=now + 40.0) == 0

    def test_at_repetitive_threshold(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=100,
            freq_repetitive_count=20,
            freq_repetitive_window_s=60.0,
        )
        now = 1000.0
        for i in range(20):
            t.record_tool_call("sess-1", "read_file", now=now + i * 2.0)
        assert t._get_frequency_d4("sess-1", now=now + 40.0) == 1

    def test_repetitive_outside_window(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=100,
            freq_repetitive_count=20,
            freq_repetitive_window_s=60.0,
        )
        now = 1000.0
        for i in range(20):
            t.record_tool_call("sess-1", "read_file", now=now + i * 2.0)
        # Way outside window
        assert t._get_frequency_d4("sess-1", now=now + 200.0) == 0

    def test_repetitive_different_tools(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=100,
            freq_repetitive_count=20,
            freq_repetitive_window_s=60.0,
        )
        now = 1000.0
        for i in range(10):
            t.record_tool_call("sess-1", "read_file", now=now + i * 2.0)
        for i in range(10):
            t.record_tool_call("sess-1", "write_file", now=now + i * 2.0)
        assert t._get_frequency_d4("sess-1", now=now + 20.0) == 0

    def test_burst_takes_priority_over_repetitive(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=10,
            freq_burst_window_s=5.0,
            freq_repetitive_count=20,
            freq_repetitive_window_s=60.0,
        )
        now = 1000.0
        # 10 calls in 1 second triggers both burst and repetitive
        for i in range(10):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        assert t._get_frequency_d4("sess-1", now=now + 1.0) == 2  # burst wins


# ---------------------------------------------------------------------------
# Rate detection
# ---------------------------------------------------------------------------


class TestRateDetection:
    """Rate: all tools >= 60 per minute → d4=1."""

    def test_below_rate_limit(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=1000,
            freq_repetitive_count=1000,
            freq_rate_limit_per_min=60,
        )
        now = 1000.0
        for i in range(59):
            t.record_tool_call("sess-1", f"tool_{i}", now=now + i * 0.5)
        assert t._get_frequency_d4("sess-1", now=now + 30.0) == 0

    def test_at_rate_limit(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=1000,
            freq_repetitive_count=1000,
            freq_rate_limit_per_min=60,
        )
        now = 1000.0
        for i in range(60):
            t.record_tool_call("sess-1", f"tool_{i % 20}", now=now + i * 0.5)
        assert t._get_frequency_d4("sess-1", now=now + 30.0) == 1

    def test_rate_different_sessions(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=1000,
            freq_repetitive_count=1000,
            freq_rate_limit_per_min=60,
        )
        now = 1000.0
        for i in range(30):
            t.record_tool_call("sess-1", f"tool_{i}", now=now + i * 0.5)
        for i in range(30):
            t.record_tool_call("sess-2", f"tool_{i}", now=now + i * 0.5)
        assert t._get_frequency_d4("sess-1", now=now + 15.0) == 0
        assert t._get_frequency_d4("sess-2", now=now + 15.0) == 0

    def test_rate_outside_window(self) -> None:
        t = SessionRiskTracker(
            freq_burst_count=1000,
            freq_repetitive_count=1000,
            freq_rate_limit_per_min=60,
        )
        now = 1000.0
        for i in range(60):
            t.record_tool_call("sess-1", f"tool_{i}", now=now + i * 0.5)
        assert t._get_frequency_d4("sess-1", now=now + 120.0) == 0


# ---------------------------------------------------------------------------
# Combined logic: max(accum, freq), capped at 2
# ---------------------------------------------------------------------------


class TestCombinedD4:
    """Final D4 = min(max(accumulation_d4, frequency_d4), 2)."""

    def test_accum_only(self) -> None:
        t = SessionRiskTracker(d4_mid_threshold=2, d4_high_threshold=5)
        t.record_high_risk_event("sess-1")
        t.record_high_risk_event("sess-1")
        assert t.get_d4("sess-1") == 1  # accum=1, freq=0

    def test_freq_only(self) -> None:
        t = SessionRiskTracker(freq_burst_count=5, freq_burst_window_s=5.0)
        now = 1000.0
        for i in range(5):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        assert t.get_d4("sess-1", now=now + 0.5) == 2  # accum=0, freq=2

    def test_both_contribute_max_wins(self) -> None:
        t = SessionRiskTracker(
            d4_mid_threshold=2,
            d4_high_threshold=5,
            freq_burst_count=5,
            freq_burst_window_s=5.0,
        )
        t.record_high_risk_event("sess-1")
        t.record_high_risk_event("sess-1")
        now = 1000.0
        for i in range(5):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        # accum=1, freq=2 → max=2
        assert t.get_d4("sess-1", now=now + 0.5) == 2

    def test_capped_at_2(self) -> None:
        t = SessionRiskTracker(
            d4_mid_threshold=2,
            d4_high_threshold=5,
            freq_burst_count=3,
            freq_burst_window_s=5.0,
        )
        # Both at max
        for _ in range(10):
            t.record_high_risk_event("sess-1")
        now = 1000.0
        for i in range(10):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        assert t.get_d4("sess-1", now=now + 1.0) == 2

    def test_disabled_freq_uses_accum_only(self) -> None:
        t = SessionRiskTracker(freq_enabled=False, d4_mid_threshold=2)
        t.record_high_risk_event("sess-1")
        t.record_high_risk_event("sess-1")
        now = 1000.0
        # Even with many tool calls, freq_d4 stays 0
        for i in range(100):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.01)
        assert t.get_d4("sess-1") == 1  # only accum


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestD4FreqConfig:
    def test_defaults(self) -> None:
        c = DetectionConfig()
        assert c.d4_freq_enabled is True
        assert c.d4_freq_burst_count == 10
        assert c.d4_freq_burst_window_s == 5.0
        assert c.d4_freq_repetitive_count == 20
        assert c.d4_freq_repetitive_window_s == 60.0
        assert c.d4_freq_rate_limit_per_min == 60

    def test_custom_values(self) -> None:
        c = DetectionConfig(d4_freq_burst_count=5, d4_freq_rate_limit_per_min=30)
        assert c.d4_freq_burst_count == 5
        assert c.d4_freq_rate_limit_per_min == 30

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CS_D4_FREQ_ENABLED", "false")
        monkeypatch.setenv("CS_D4_FREQ_BURST_COUNT", "5")
        monkeypatch.setenv("CS_D4_FREQ_RATE_LIMIT_PER_MIN", "30")
        c = build_detection_config_from_env()
        assert c.d4_freq_enabled is False
        assert c.d4_freq_burst_count == 5
        assert c.d4_freq_rate_limit_per_min == 30


# ---------------------------------------------------------------------------
# Memory / reset
# ---------------------------------------------------------------------------


class TestD4FreqMemory:
    def test_reset_clears_frequency(self) -> None:
        t = SessionRiskTracker(freq_burst_count=5, freq_burst_window_s=5.0)
        now = 1000.0
        for i in range(5):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        assert t._get_frequency_d4("sess-1", now=now + 0.5) == 2
        t.reset_session("sess-1")
        assert t._get_frequency_d4("sess-1", now=now + 0.5) == 0

    def test_eviction_clears_frequency(self) -> None:
        t = SessionRiskTracker(
            max_sessions=2,
            freq_burst_count=3,
            freq_burst_window_s=5.0,
        )
        now = 1000.0
        for i in range(3):
            t.record_tool_call("sess-1", "bash", now=now + i * 0.1)
        t.record_high_risk_event("sess-1")
        # Add new sessions to trigger eviction
        t.record_high_risk_event("sess-2")
        t.record_high_risk_event("sess-3")
        # sess-1 should have been evicted
        assert t._get_frequency_d4("sess-1", now=now + 1.0) == 0
