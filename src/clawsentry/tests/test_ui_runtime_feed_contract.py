"""Static contract tests for the dashboard runtime feed.

These tests intentionally verify source-level UI contracts because the repo
does not currently include a browser/component test harness for the React app.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "ui" / "src"


def test_dashboard_uses_runtime_feed_component() -> None:
    source = (ROOT / "pages" / "Dashboard.tsx").read_text()
    assert "RuntimeFeed" in source


def test_runtime_feed_subscribes_to_key_runtime_event_types() -> None:
    source = (ROOT / "components" / "RuntimeFeed.tsx").read_text()
    for event_type in (
        "decision",
        "alert",
        "trajectory_alert",
        "post_action_finding",
        "pattern_candidate",
        "pattern_evolved",
        "defer_pending",
        "defer_resolved",
        "session_enforcement_change",
    ):
        assert f"'{event_type}'" in source
