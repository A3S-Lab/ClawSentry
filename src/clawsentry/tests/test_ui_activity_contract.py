from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
UI_ROOT = REPO_ROOT / "src" / "clawsentry" / "ui" / "src"


def _read_ui_file(relative_path: str) -> str:
    return (UI_ROOT / relative_path).read_text(encoding="utf-8")


def test_dashboard_feed_subscribes_to_runtime_activity_events() -> None:
    source = _read_ui_file("components/RuntimeFeed.tsx")

    assert "Live Activity Feed" in source
    assert "trajectory_alert" in source
    assert "post_action_finding" in source
    assert "pattern_candidate" in source
    assert "pattern_evolved" in source
    assert "defer_pending" in source
    assert "defer_resolved" in source
    assert "session_enforcement_change" in source
    assert "alert" in source


def test_dashboard_highlights_framework_workspace_monitoring() -> None:
    source = _read_ui_file("pages/Dashboard.tsx")

    assert "Framework Coverage" in source
    assert "Workspace Risk Board" in source


def test_defer_panel_uses_explicit_defer_lifecycle_events() -> None:
    source = _read_ui_file("pages/DeferPanel.tsx")

    assert "connectSSE(['defer_pending', 'defer_resolved'])" in source
