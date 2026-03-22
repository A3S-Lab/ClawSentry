"""
Unit tests for gateway/models.py — Gate 1 verification.

Covers: field validation, sentinel values, schema_version format,
conditional fields, enum constraints, SyncDecision envelopes.
"""

import pytest
from pydantic import ValidationError

from clawsentry.gateway.models import (
    CanonicalEvent,
    CanonicalDecision,
    RiskSnapshot,
    RiskDimensions,
    SyncDecisionRequest,
    SyncDecisionResponse,
    SyncDecisionErrorResponse,
    EventType,
    DecisionVerdict,
    DecisionSource,
    RiskLevel,
    FailureClass,
    DecisionTier,
    RPCErrorCode,
    ClassifiedBy,
    AgentTrustLevel,
    CURRENT_SCHEMA_VERSION,
    RPC_VERSION,
    utc_now_iso,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_event(**overrides) -> dict:
    base = {
        "event_id": "evt-001",
        "trace_id": "trace-001",
        "event_type": "pre_action",
        "session_id": "sess-001",
        "agent_id": "agent-001",
        "source_framework": "test",
        "occurred_at": "2026-03-19T12:00:00+00:00",
        "payload": {"tool": "bash", "command": "ls"},
    }
    base.update(overrides)
    return base


def _minimal_decision(**overrides) -> dict:
    base = {
        "decision": "allow",
        "reason": "Safe read-only operation",
        "policy_id": "L1-safe-baseline",
        "risk_level": "low",
        "decision_source": "policy",
    }
    base.update(overrides)
    return base


def _minimal_risk_snapshot(**overrides) -> dict:
    base = {
        "risk_level": "low",
        "composite_score": 0,
        "dimensions": {"d1": 0, "d2": 0, "d3": 0, "d4": 0, "d5": 0},
        "short_circuit_rule": None,
        "missing_dimensions": [],
        "classified_by": "L1",
        "classified_at": "2026-03-19T12:00:00+00:00",
    }
    base.update(overrides)
    return base


# ===========================================================================
# CanonicalEvent Tests
# ===========================================================================

class TestCanonicalEvent:
    def test_valid_minimal_event(self):
        evt = CanonicalEvent(**_minimal_event())
        assert evt.schema_version == CURRENT_SCHEMA_VERSION
        assert evt.event_type == EventType.PRE_ACTION

    def test_all_event_types(self):
        for et in EventType:
            evt = CanonicalEvent(**_minimal_event(event_type=et.value))
            assert evt.event_type == et

    def test_invalid_event_type(self):
        with pytest.raises(ValidationError):
            CanonicalEvent(**_minimal_event(event_type="unknown"))

    def test_schema_version_valid(self):
        evt = CanonicalEvent(**_minimal_event(schema_version="ahp.2.1"))
        assert evt.schema_version == "ahp.2.1"

    def test_schema_version_invalid(self):
        with pytest.raises(ValidationError, match="schema_version"):
            CanonicalEvent(**_minimal_event(schema_version="ahp.v1"))

    def test_schema_version_invalid_format(self):
        with pytest.raises(ValidationError):
            CanonicalEvent(**_minimal_event(schema_version="v1.0"))

    def test_empty_event_id_rejected(self):
        with pytest.raises(ValidationError):
            CanonicalEvent(**_minimal_event(event_id=""))

    def test_empty_trace_id_rejected(self):
        with pytest.raises(ValidationError):
            CanonicalEvent(**_minimal_event(trace_id=""))

    def test_occurred_at_invalid(self):
        with pytest.raises(ValidationError, match="occurred_at"):
            CanonicalEvent(**_minimal_event(occurred_at="not-a-date"))

    def test_occurred_at_with_z_suffix(self):
        evt = CanonicalEvent(**_minimal_event(occurred_at="2026-03-19T12:00:00Z"))
        assert evt.occurred_at == "2026-03-19T12:00:00Z"

    def test_sentinel_session_id(self):
        sid = CanonicalEvent.sentinel_session_id("a3s-code")
        assert sid == "unknown_session:a3s-code"

    def test_sentinel_agent_id(self):
        aid = CanonicalEvent.sentinel_agent_id("openclaw")
        assert aid == "unknown_agent:openclaw"

    def test_a3s_code_requires_event_subtype(self):
        with pytest.raises(ValidationError, match="event_subtype"):
            CanonicalEvent(**_minimal_event(source_framework="a3s-code"))

    def test_a3s_code_with_event_subtype(self):
        evt = CanonicalEvent(**_minimal_event(
            source_framework="a3s-code",
            event_subtype="PreToolUse",
        ))
        assert evt.event_subtype == "PreToolUse"

    def test_openclaw_requires_protocol_and_profile(self):
        with pytest.raises(ValidationError, match="source_protocol_version"):
            CanonicalEvent(**_minimal_event(
                source_framework="openclaw",
                event_subtype="command:new",
            ))

    def test_openclaw_valid(self):
        evt = CanonicalEvent(**_minimal_event(
            source_framework="openclaw",
            event_subtype="command:new",
            source_protocol_version="1.0",
            mapping_profile="openclaw@5625cf4/protocol.v1/profile.v1",
        ))
        assert evt.mapping_profile.startswith("openclaw@")

    def test_openclaw_invalid_mapping_profile_rejected(self):
        with pytest.raises(ValidationError, match="mapping_profile"):
            CanonicalEvent(**_minimal_event(
                source_framework="openclaw",
                event_subtype="command:new",
                source_protocol_version="1.0",
                mapping_profile="openclaw@bad/profile.v1",
            ))

    def test_optional_fields_default(self):
        evt = CanonicalEvent(**_minimal_event())
        assert evt.parent_event_id is None
        assert evt.depth is None
        assert evt.tool_name is None
        assert evt.risk_hints == []
        assert evt.framework_meta is None

    def test_depth_negative_rejected(self):
        with pytest.raises(ValidationError):
            CanonicalEvent(**_minimal_event(depth=-1))


# ===========================================================================
# CanonicalDecision Tests
# ===========================================================================

class TestCanonicalDecision:
    def test_valid_allow(self):
        d = CanonicalDecision(**_minimal_decision())
        assert d.decision == DecisionVerdict.ALLOW
        assert d.final is True  # auto-set for allow

    def test_valid_block(self):
        d = CanonicalDecision(**_minimal_decision(decision="block"))
        assert d.final is True

    def test_allow_final_false_rejected(self):
        with pytest.raises(ValidationError, match="final"):
            CanonicalDecision(**_minimal_decision(final=False))

    def test_block_final_false_rejected(self):
        with pytest.raises(ValidationError, match="final"):
            CanonicalDecision(**_minimal_decision(decision="block", final=False))

    def test_defer_no_final_required(self):
        d = CanonicalDecision(**_minimal_decision(decision="defer"))
        assert d.final is None  # not auto-set for defer

    def test_modify_with_payload(self):
        d = CanonicalDecision(**_minimal_decision(
            decision="modify",
            modified_payload={"sanitized": True},
        ))
        assert d.modified_payload == {"sanitized": True}

    def test_modify_without_payload_rejected(self):
        with pytest.raises(ValidationError, match="modified_payload"):
            CanonicalDecision(**_minimal_decision(decision="modify"))

    def test_all_failure_classes(self):
        for fc in FailureClass:
            d = CanonicalDecision(**_minimal_decision(failure_class=fc.value))
            assert d.failure_class == fc

    def test_all_decision_sources(self):
        for ds in DecisionSource:
            d = CanonicalDecision(**_minimal_decision(decision_source=ds.value))
            assert d.decision_source == ds


# ===========================================================================
# RiskSnapshot Tests
# ===========================================================================

class TestRiskSnapshot:
    def test_valid_minimal(self):
        rs = RiskSnapshot(**_minimal_risk_snapshot())
        assert rs.risk_level == RiskLevel.LOW
        assert rs.composite_score == 0

    def test_all_risk_levels(self):
        for rl in RiskLevel:
            rs = RiskSnapshot(**_minimal_risk_snapshot(risk_level=rl.value))
            assert rs.risk_level == rl

    def test_valid_short_circuit_rules(self):
        for sc in ("SC-1", "SC-2", "SC-3"):
            rs = RiskSnapshot(**_minimal_risk_snapshot(
                short_circuit_rule=sc,
                risk_level="critical",
                composite_score=7,
            ))
            assert rs.short_circuit_rule == sc

    def test_invalid_short_circuit_rule(self):
        with pytest.raises(ValidationError, match="short_circuit_rule"):
            RiskSnapshot(**_minimal_risk_snapshot(short_circuit_rule="SC-99"))

    def test_dimension_bounds(self):
        # d1-d3: 0-3, d4-d5: 0-2
        rs = RiskSnapshot(**_minimal_risk_snapshot(
            dimensions={"d1": 3, "d2": 3, "d3": 3, "d4": 2, "d5": 2},
            composite_score=7,
            risk_level="critical",
        ))
        assert rs.dimensions.d1 == 3

    def test_dimension_d1_out_of_bounds(self):
        with pytest.raises(ValidationError):
            RiskSnapshot(**_minimal_risk_snapshot(
                dimensions={"d1": 4, "d2": 0, "d3": 0, "d4": 0, "d5": 0},
            ))

    def test_dimension_d4_out_of_bounds(self):
        with pytest.raises(ValidationError):
            RiskSnapshot(**_minimal_risk_snapshot(
                dimensions={"d1": 0, "d2": 0, "d3": 0, "d4": 3, "d5": 0},
            ))

    def test_missing_dimensions_list(self):
        rs = RiskSnapshot(**_minimal_risk_snapshot(
            missing_dimensions=["d1", "d5"],
        ))
        assert rs.missing_dimensions == ["d1", "d5"]

    def test_classified_at_invalid(self):
        with pytest.raises(ValidationError, match="classified_at"):
            RiskSnapshot(**_minimal_risk_snapshot(classified_at="bad-date"))

    def test_l1_snapshot_nesting(self):
        inner = _minimal_risk_snapshot()
        rs = RiskSnapshot(**_minimal_risk_snapshot(
            risk_level="high",
            composite_score=4,
            classified_by="L2",
            l1_snapshot=inner,
        ))
        assert rs.l1_snapshot is not None
        assert rs.l1_snapshot.classified_by == ClassifiedBy.L1

    def test_composite_score_out_of_bounds(self):
        with pytest.raises(ValidationError):
            RiskSnapshot(**_minimal_risk_snapshot(composite_score=8))

    def test_composite_score_max_valid(self):
        rs = RiskSnapshot(**_minimal_risk_snapshot(
            composite_score=7,
            risk_level="critical",
            dimensions={"d1": 3, "d2": 3, "d3": 3, "d4": 2, "d5": 2},
        ))
        assert rs.composite_score == 7


# ===========================================================================
# SyncDecision RPC Tests
# ===========================================================================

class TestSyncDecisionRequest:
    def test_valid_request(self):
        req = SyncDecisionRequest(
            request_id="req-001",
            deadline_ms=100,
            decision_tier=DecisionTier.L1,
            event=CanonicalEvent(**_minimal_event()),
        )
        assert req.rpc_version == RPC_VERSION
        assert req.deadline_ms == 100

    def test_invalid_rpc_version_accepted_at_model_level(self):
        """rpc_version validation moved to gateway level (VERSION_NOT_SUPPORTED)."""
        req = SyncDecisionRequest(
            rpc_version="bad",
            request_id="req-001",
            deadline_ms=100,
            decision_tier=DecisionTier.L1,
            event=CanonicalEvent(**_minimal_event()),
        )
        assert req.rpc_version == "bad"

    def test_deadline_exceeds_hard_limit(self):
        with pytest.raises(ValidationError):
            SyncDecisionRequest(
                request_id="req-001",
                deadline_ms=6000,
                decision_tier=DecisionTier.L1,
                event=CanonicalEvent(**_minimal_event()),
            )

    def test_deadline_zero_rejected(self):
        with pytest.raises(ValidationError):
            SyncDecisionRequest(
                request_id="req-001",
                deadline_ms=0,
                decision_tier=DecisionTier.L1,
                event=CanonicalEvent(**_minimal_event()),
            )

    def test_with_context(self):
        req = SyncDecisionRequest(
            request_id="req-001",
            deadline_ms=100,
            decision_tier=DecisionTier.L1,
            event=CanonicalEvent(**_minimal_event()),
            context={
                "agent_trust_level": "standard",
                "workspace_id": "ws-001",
            },
        )
        assert req.context.agent_trust_level == AgentTrustLevel.STANDARD


class TestSyncDecisionResponse:
    def test_valid_response(self):
        resp = SyncDecisionResponse(
            request_id="req-001",
            decision=CanonicalDecision(**_minimal_decision()),
            actual_tier=DecisionTier.L1,
            served_at="2026-03-19T12:00:00+00:00",
        )
        assert resp.rpc_status == "ok"

    def test_rpc_status_must_be_ok(self):
        with pytest.raises(ValidationError, match="rpc_status"):
            SyncDecisionResponse(
                request_id="req-001",
                rpc_status="error",
                decision=CanonicalDecision(**_minimal_decision()),
                actual_tier=DecisionTier.L1,
                served_at="2026-03-19T12:00:00+00:00",
            )

    def test_served_at_invalid_rejected(self):
        with pytest.raises(ValidationError, match="served_at"):
            SyncDecisionResponse(
                request_id="req-001",
                decision=CanonicalDecision(**_minimal_decision()),
                actual_tier=DecisionTier.L1,
                served_at="not-a-date",
            )


class TestSyncDecisionErrorResponse:
    def test_valid_error_response(self):
        err = SyncDecisionErrorResponse(
            request_id="req-001",
            rpc_error_code=RPCErrorCode.DEADLINE_EXCEEDED,
            rpc_error_message="L2 analysis timed out",
            retry_eligible=True,
            retry_after_ms=50,
        )
        assert err.rpc_status == "error"
        assert err.retry_eligible is True

    def test_retry_eligible_requires_retry_after_ms(self):
        with pytest.raises(ValidationError, match="retry_after_ms"):
            SyncDecisionErrorResponse(
                request_id="req-001",
                rpc_error_code=RPCErrorCode.DEADLINE_EXCEEDED,
                rpc_error_message="timeout",
                retry_eligible=True,
                # missing retry_after_ms
            )

    def test_non_retryable_error(self):
        err = SyncDecisionErrorResponse(
            request_id="req-001",
            rpc_error_code=RPCErrorCode.INVALID_REQUEST,
            rpc_error_message="Missing event field",
            retry_eligible=False,
        )
        assert err.retry_after_ms is None

    def test_all_error_codes(self):
        for code in RPCErrorCode:
            err = SyncDecisionErrorResponse(
                request_id="req-001",
                rpc_error_code=code,
                rpc_error_message="test",
                retry_eligible=False,
            )
            assert err.rpc_error_code == code

    def test_with_fallback_decision(self):
        err = SyncDecisionErrorResponse(
            request_id="req-001",
            rpc_error_code=RPCErrorCode.ENGINE_UNAVAILABLE,
            rpc_error_message="Engine down",
            retry_eligible=True,
            retry_after_ms=100,
            fallback_decision=CanonicalDecision(**_minimal_decision(
                decision="block",
                decision_source="system",
                reason="Engine unavailable, fail-closed",
            )),
        )
        assert err.fallback_decision.decision == DecisionVerdict.BLOCK


# ===========================================================================
# Utility Tests
# ===========================================================================

class TestRiskSnapshotL3Trace:
    def test_risk_snapshot_l3_trace_default_none(self):
        snap = RiskSnapshot(
            risk_level=RiskLevel.LOW,
            composite_score=1,
            dimensions=RiskDimensions(d1=1, d2=0, d3=0, d4=0, d5=0),
            classified_by=ClassifiedBy.L1,
            classified_at="2026-03-21T00:00:00+00:00",
        )
        assert snap.l3_trace is None

    def test_risk_snapshot_l3_trace_excluded_from_dump(self):
        trace = {"trigger_reason": "test", "turns": []}
        snap = RiskSnapshot(
            risk_level=RiskLevel.LOW,
            composite_score=1,
            dimensions=RiskDimensions(d1=1, d2=0, d3=0, d4=0, d5=0),
            classified_by=ClassifiedBy.L1,
            classified_at="2026-03-21T00:00:00+00:00",
            l3_trace=trace,
        )
        assert snap.l3_trace == trace
        dumped = snap.model_dump(mode="json")
        assert "l3_trace" not in dumped


class TestUtilities:
    def test_utc_now_iso(self):
        ts = utc_now_iso()
        # Should be parseable and contain timezone info
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None
