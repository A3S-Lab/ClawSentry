"""Tests for AgentAnalyzer MVP behavior."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from clawsentry.gateway.agent_analyzer import AgentAnalyzer, AgentAnalyzerConfig
from clawsentry.gateway.l3_trigger import L3TriggerPolicy
from clawsentry.gateway.models import (
    CanonicalEvent,
    ClassifiedBy,
    DecisionContext,
    EventType,
    RiskDimensions,
    RiskLevel,
    RiskSnapshot,
)
from clawsentry.gateway.review_skills import SkillRegistry
from clawsentry.gateway.review_toolkit import ReadOnlyToolkit


class StubTrajectoryStore:
    def replay_session(self, session_id, limit=100):
        return [
            {
                "recorded_at": "2026-03-21T12:00:00+00:00",
                "event": {
                    "session_id": session_id,
                    "tool_name": "bash",
                    "event_type": "pre_action",
                    "risk_hints": ["credential_exfiltration"],
                },
                "decision": {"risk_level": "high"},
            }
        ]


def _evt(tool_name=None, payload=None, risk_hints=None) -> CanonicalEvent:
    return CanonicalEvent(
        event_id="evt-agent-analyzer",
        trace_id="trace-agent-analyzer",
        event_type=EventType.PRE_ACTION,
        session_id="sess-agent-analyzer",
        agent_id="agent-agent-analyzer",
        source_framework="test",
        occurred_at="2026-03-21T12:00:00+00:00",
        payload=payload or {},
        tool_name=tool_name,
        risk_hints=risk_hints or [],
    )


def _snap(level: RiskLevel = RiskLevel.MEDIUM) -> RiskSnapshot:
    return RiskSnapshot(
        risk_level=level,
        composite_score=2,
        dimensions=RiskDimensions(d1=1, d2=0, d3=0, d4=0, d5=1),
        classified_by=ClassifiedBy.L1,
        classified_at="2026-03-21T12:00:00+00:00",
    )


def _skills_dir(tmp_path: Path) -> Path:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "credential-audit.yaml").write_text(
        """
name: credential-audit
description: 审查凭证相关操作
triggers:
  risk_hints:
    - credential_exfiltration
  tool_names:
    - bash
  payload_patterns:
    - token
system_prompt: |
  你是一个凭证审查专家。
evaluation_criteria:
  - name: credential_exposure
    severity: critical
    description: 凭证内容是否被暴露
""".strip(),
        encoding="utf-8",
    )
    (skills_dir / "general-review.yaml").write_text(
        """
name: general-review
description: 通用兜底审查
triggers:
  risk_hints: []
  tool_names: []
  payload_patterns: []
system_prompt: |
  你是一个通用安全审查专家。
evaluation_criteria:
  - name: general_risk
    severity: medium
    description: 整体风险评估
""".strip(),
        encoding="utf-8",
    )
    return skills_dir


def test_mvp_returns_degraded_result_when_trigger_not_matched(tmp_path: Path):
    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(return_value='{"risk_level": "critical", "findings": ["x"], "confidence": 0.9}')
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider,
        toolkit=toolkit,
        skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=False, initial_trajectory_limit=5),
    )

    result = asyncio.run(
        analyzer.analyze(
            _evt(tool_name="read_file", payload={"path": "README.md"}, risk_hints=[]),
            DecisionContext(),
            _snap(RiskLevel.MEDIUM),
            3000,
        )
    )

    assert result.target_level == RiskLevel.MEDIUM
    assert result.confidence == 0.0


def test_mvp_returns_llm_result_when_trigger_matches(tmp_path: Path):
    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(
        return_value='{"risk_level": "high", "findings": ["credential access looks suspicious"], "confidence": 0.82}'
    )
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider,
        toolkit=toolkit,
        skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=False, initial_trajectory_limit=5),
    )

    result = asyncio.run(
        analyzer.analyze(
            _evt(
                tool_name="bash",
                payload={"command": "cat api_token.txt"},
                risk_hints=["credential_exfiltration"],
            ),
            DecisionContext(session_risk_summary={"l3_escalate": True}),
            _snap(RiskLevel.MEDIUM),
            3000,
        )
    )

    assert result.target_level == RiskLevel.HIGH
    assert result.confidence == 0.82
    assert result.analyzer_id == "agent-reviewer"
    assert "credential access looks suspicious" in result.reasons


def test_multi_turn_executes_tool_call_then_final_response(tmp_path: Path):
    # Round 1: LLM requests a tool call
    # Round 2: LLM returns final result after seeing tool output
    tool_call_response = '{"thought": "need to read the file", "tool_call": {"name": "read_file", "arguments": {"relative_path": "secrets.env"}}, "done": false}'
    final_response = '{"risk_level": "critical", "findings": ["found credentials in secrets.env"], "confidence": 0.95}'

    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(side_effect=[tool_call_response, final_response])

    (tmp_path / "secrets.env").write_text("API_KEY=abc123", encoding="utf-8")
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider,
        toolkit=toolkit,
        skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=True, initial_trajectory_limit=5, max_reasoning_turns=4),
    )

    result = asyncio.run(
        analyzer.analyze(
            _evt(
                tool_name="bash",
                payload={"command": "cat secrets.env"},
                risk_hints=["credential_exfiltration"],
            ),
            DecisionContext(session_risk_summary={"l3_escalate": True}),
            _snap(RiskLevel.MEDIUM),
            10000,
        )
    )

    assert result.target_level == RiskLevel.CRITICAL
    assert result.confidence == 0.95
    assert "found credentials in secrets.env" in result.reasons
    assert provider.complete.call_count == 2


def test_multi_turn_degrades_on_invalid_tool_name(tmp_path: Path):
    tool_call_with_bad_tool = '{"thought": "try to write", "tool_call": {"name": "write_file", "arguments": {"path": "x"}}, "done": false}'
    final_response = '{"risk_level": "high", "findings": ["fallback"], "confidence": 0.5}'

    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(side_effect=[tool_call_with_bad_tool, final_response])

    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider,
        toolkit=toolkit,
        skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=True, initial_trajectory_limit=5, max_reasoning_turns=4),
    )

    result = asyncio.run(
        analyzer.analyze(
            _evt(tool_name="bash", risk_hints=["credential_exfiltration"]),
            DecisionContext(session_risk_summary={"l3_escalate": True}),
            _snap(RiskLevel.MEDIUM),
            10000,
        )
    )

    # write_file is not in toolkit whitelist — should degrade
    assert result.target_level == RiskLevel.MEDIUM
    assert result.confidence == 0.0


def test_multi_turn_stops_at_max_turns(tmp_path: Path):
    # LLM always returns tool_call, never done=True
    tool_call_loop = '{"thought": "keep going", "tool_call": {"name": "list_directory", "arguments": {"relative_path": "."}}, "done": false}'

    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(return_value=tool_call_loop)

    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider,
        toolkit=toolkit,
        skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=True, initial_trajectory_limit=5, max_reasoning_turns=3),
    )

    result = asyncio.run(
        analyzer.analyze(
            _evt(tool_name="bash", risk_hints=["credential_exfiltration"]),
            DecisionContext(session_risk_summary={"l3_escalate": True}),
            _snap(RiskLevel.MEDIUM),
            10000,
        )
    )

    assert result.confidence == 0.0
    assert result.target_level == RiskLevel.MEDIUM


def test_mvp_trace_recorded_on_degraded(tmp_path: Path):
    """When L3 trigger not matched, trace records degradation reason."""
    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(return_value='{}')
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider, toolkit=toolkit, skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=False),
    )
    result = asyncio.run(
        analyzer.analyze(
            _evt(tool_name="read_file", risk_hints=[]),
            DecisionContext(),
            _snap(RiskLevel.MEDIUM),
            3000,
        )
    )
    assert result.trace is not None
    assert result.trace["degraded"] is True
    assert result.trace["trigger_reason"] == "trigger_not_matched"
    assert result.trace["turns"] == []


def test_mvp_trace_recorded_on_single_turn_success(tmp_path: Path):
    """Single-turn MVP records skill, LLM call, and final verdict in trace."""
    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(
        return_value='{"risk_level": "high", "findings": ["suspicious"], "confidence": 0.82}'
    )
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider, toolkit=toolkit, skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=False),
    )
    result = asyncio.run(
        analyzer.analyze(
            _evt(tool_name="bash", payload={"command": "cat token.txt"},
                 risk_hints=["credential_exfiltration"]),
            DecisionContext(session_risk_summary={"l3_escalate": True}),
            _snap(RiskLevel.MEDIUM),
            3000,
        )
    )
    assert result.trace is not None
    assert result.trace["degraded"] is False
    assert result.trace["mode"] == "single_turn"
    assert result.trace["skill_selected"] == "credential-audit"
    assert len(result.trace["turns"]) == 1
    assert result.trace["turns"][0]["type"] == "llm_call"
    assert result.trace["final_verdict"]["risk_level"] == "high"
    assert result.trace["final_verdict"]["confidence"] == 0.82


def test_multi_turn_trace_records_tool_calls(tmp_path: Path):
    """Multi-turn mode records each LLM call and tool call in trace."""
    tool_call_resp = '{"thought": "check file", "tool_call": {"name": "read_file", "arguments": {"relative_path": "secrets.env"}}, "done": false}'
    final_resp = '{"risk_level": "critical", "findings": ["creds found"], "confidence": 0.95}'

    provider = MagicMock()
    provider.provider_id = "mock-llm"
    provider.complete = AsyncMock(side_effect=[tool_call_resp, final_resp])

    (tmp_path / "secrets.env").write_text("API_KEY=abc123", encoding="utf-8")
    toolkit = ReadOnlyToolkit(tmp_path, StubTrajectoryStore())
    registry = SkillRegistry(_skills_dir(tmp_path))
    analyzer = AgentAnalyzer(
        provider=provider, toolkit=toolkit, skill_registry=registry,
        trigger_policy=L3TriggerPolicy(),
        config=AgentAnalyzerConfig(enable_multi_turn=True, max_reasoning_turns=4),
    )
    result = asyncio.run(
        analyzer.analyze(
            _evt(tool_name="bash", payload={"command": "cat secrets.env"},
                 risk_hints=["credential_exfiltration"]),
            DecisionContext(session_risk_summary={"l3_escalate": True}),
            _snap(RiskLevel.MEDIUM),
            10000,
        )
    )
    assert result.trace is not None
    assert result.trace["mode"] == "multi_turn"
    assert result.trace["degraded"] is False
    turns = result.trace["turns"]
    assert len(turns) >= 3  # llm_call, tool_call, llm_call
    assert turns[0]["type"] == "llm_call"
    assert turns[1]["type"] == "tool_call"
    assert turns[1]["tool_name"] == "read_file"
    assert turns[2]["type"] == "llm_call"
    assert result.trace["tool_calls_used"] == 1
    assert result.trace["final_verdict"]["risk_level"] == "critical"
