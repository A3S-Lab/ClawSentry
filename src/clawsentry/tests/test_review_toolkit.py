"""Tests for ReadOnlyToolkit."""

from pathlib import Path

import pytest

from clawsentry.gateway.review_toolkit import ReadOnlyToolkit


class StubTrajectoryStore:
    def replay_session(self, session_id, limit=100):
        return [
            {
                "recorded_at": "2026-03-21T12:00:00+00:00",
                "event": {"session_id": session_id, "tool_name": "bash"},
                "decision": {"risk_level": "high"},
            }
            for _ in range(limit)
        ]


@pytest.mark.asyncio
async def test_read_file_rejects_path_escape(tmp_path: Path):
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())

    result = await toolkit.read_file("../outside.txt")

    assert result.startswith("[error:")
    assert "escapes workspace_root" in result


@pytest.mark.asyncio
async def test_read_trajectory_caps_limit_to_max_events(tmp_path: Path):
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())

    result = await toolkit.read_trajectory("sess-1", limit=1000)

    assert len(result) == toolkit.MAX_TRAJECTORY_EVENTS


@pytest.mark.asyncio
async def test_budget_is_enforced(tmp_path: Path):
    (tmp_path / "demo.txt").write_text("hello", encoding="utf-8")
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())

    for _ in range(toolkit.MAX_TOOL_CALLS):
        await toolkit.read_file("demo.txt")

    with pytest.raises(Exception):
        await toolkit.read_file("demo.txt")
