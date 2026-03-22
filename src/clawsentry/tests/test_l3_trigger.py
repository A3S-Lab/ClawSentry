"""Tests for L3TriggerPolicy."""

from clawsentry.gateway.l3_trigger import L3TriggerPolicy
from clawsentry.gateway.models import (
    CanonicalEvent,
    DecisionContext,
    EventType,
    RiskDimensions,
    RiskLevel,
    RiskSnapshot,
    ClassifiedBy,
)


def _evt(tool_name=None, payload=None, risk_hints=None) -> CanonicalEvent:
    return CanonicalEvent(
        event_id="evt-l3-trigger",
        trace_id="trace-l3-trigger",
        event_type=EventType.PRE_ACTION,
        session_id="sess-l3-trigger",
        agent_id="agent-l3-trigger",
        source_framework="test",
        occurred_at="2026-03-21T12:00:00+00:00",
        payload=payload or {},
        tool_name=tool_name,
        risk_hints=risk_hints or [],
    )


def _snap(level: RiskLevel) -> RiskSnapshot:
    return RiskSnapshot(
        risk_level=level,
        composite_score=2,
        dimensions=RiskDimensions(d1=1, d2=0, d3=0, d4=0, d5=1),
        classified_by=ClassifiedBy.L1,
        classified_at="2026-03-21T12:00:00+00:00",
    )


def test_triggers_on_manual_l3_escalation_flag():
    policy = L3TriggerPolicy()
    ctx = DecisionContext(session_risk_summary={"l3_escalate": True})

    result = policy.should_trigger(
        _evt(tool_name="read_file"),
        ctx,
        _snap(RiskLevel.MEDIUM),
        [],
    )

    assert result is True


def test_triggers_on_cumulative_risk_threshold():
    policy = L3TriggerPolicy()

    result = policy.should_trigger(
        _evt(tool_name="read_file"),
        DecisionContext(),
        _snap(RiskLevel.MEDIUM),
        [
            _snap(RiskLevel.HIGH),
            _snap(RiskLevel.HIGH),
            _snap(RiskLevel.MEDIUM),
        ],
    )

    assert result is True


def test_triggers_on_high_risk_tool_with_complex_payload():
    policy = L3TriggerPolicy()
    payload = {
        "command": "python -c 'print(1)'",
        "steps": [{"cmd": "echo x"}] * 80,
    }

    result = policy.should_trigger(
        _evt(tool_name="bash", payload=payload),
        DecisionContext(),
        _snap(RiskLevel.MEDIUM),
        [],
    )

    assert result is True
