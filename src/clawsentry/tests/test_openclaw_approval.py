"""
Tests for OpenClaw Approval State Machine — Gate 2 verification.

Covers: State transitions, retry budget, failure_class assignment,
risk_level guards, terminal states.
"""

import pytest

from clawsentry.adapters.openclaw_approval import (
    ApprovalState,
    ApprovalStateMachine,
    ApprovalRecord,
    RetryBudget,
    RETRY_BUDGET_BY_RISK,
)
from clawsentry.gateway.models import (
    DecisionVerdict,
    FailureClass,
    RiskLevel,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sm():
    return ApprovalStateMachine(max_retry_budget=3)


# ===========================================================================
# Basic State Transitions (07 section 6.1)
# ===========================================================================

class TestBasicTransitions:
    def test_initial_state_is_requested(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        assert record.state == ApprovalState.REQUESTED

    def test_requested_to_pending(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        assert record.state == ApprovalState.PENDING

    def test_allow_once_resolves_to_terminal_allow(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw="allow-once")
        assert record.state == ApprovalState.TERMINAL_ALLOW
        assert record.decision_mapped == DecisionVerdict.ALLOW
        assert record.failure_class == FailureClass.NONE

    def test_allow_always_resolves_to_terminal_allow(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.LOW)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw="allow-always")
        assert record.state == ApprovalState.TERMINAL_ALLOW
        assert record.decision_mapped == DecisionVerdict.ALLOW

    def test_deny_resolves_to_terminal_block(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw="deny")
        assert record.state == ApprovalState.TERMINAL_BLOCK
        assert record.decision_mapped == DecisionVerdict.BLOCK
        assert record.failure_class == FailureClass.NONE


# ===========================================================================
# Timeout (decision=null) Transitions
# ===========================================================================

class TestTimeoutTransitions:
    def test_timeout_defers(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)
        assert record.state == ApprovalState.DEFERRED
        assert record.failure_class == FailureClass.APPROVAL_TIMEOUT

    def test_timeout_high_risk_blocks_after_budget(self, sm):
        """High-risk timeout with exhausted budget → terminal_block."""
        sm_small = ApprovalStateMachine(max_retry_budget=1)
        record = sm_small.create("ap-1", risk_level=RiskLevel.HIGH)
        sm_small.transition_to_pending(record)
        # First timeout: deferred
        sm_small.resolve(record, decision_raw=None)
        assert record.state == ApprovalState.DEFERRED
        # Retry
        sm_small.retry(record)
        sm_small.transition_to_pending(record)
        sm_small.resolve(record, decision_raw=None)
        # Budget exhausted + high risk → block
        assert record.state == ApprovalState.TERMINAL_BLOCK


# ===========================================================================
# No-Route Transitions
# ===========================================================================

class TestNoRouteTransitions:
    def test_no_route_high_risk_blocks(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.HIGH)
        sm.transition_to_pending(record)
        sm.no_route(record)
        assert record.state == ApprovalState.TERMINAL_BLOCK
        assert record.failure_class == FailureClass.APPROVAL_NO_ROUTE

    def test_no_route_critical_risk_blocks(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.CRITICAL)
        sm.transition_to_pending(record)
        sm.no_route(record)
        assert record.state == ApprovalState.TERMINAL_BLOCK

    def test_no_route_medium_risk_defers(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        sm.no_route(record)
        assert record.state == ApprovalState.DEFERRED
        assert record.failure_class == FailureClass.APPROVAL_NO_ROUTE

    def test_no_route_low_risk_defers(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.LOW)
        sm.transition_to_pending(record)
        sm.no_route(record)
        assert record.state == ApprovalState.DEFERRED


# ===========================================================================
# Retry Budget
# ===========================================================================

class TestRetryBudget:
    def test_retry_increments_budget(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)
        assert record.retry_budget_used == 0
        sm.retry(record)
        assert record.retry_budget_used == 1

    def test_budget_exhausted_medium_defers_terminal(self, sm):
        """Medium risk with exhausted budget → terminal_defer."""
        sm_small = ApprovalStateMachine(max_retry_budget=1)
        record = sm_small.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm_small.transition_to_pending(record)
        sm_small.resolve(record, decision_raw=None)
        sm_small.retry(record)
        sm_small.transition_to_pending(record)
        sm_small.resolve(record, decision_raw=None)
        # Budget exceeded + medium risk → terminal_defer
        assert record.state == ApprovalState.TERMINAL_DEFER

    def test_budget_exhausted_critical_blocks(self, sm):
        """Critical risk with exhausted budget → terminal_block."""
        sm_small = ApprovalStateMachine(max_retry_budget=1)
        record = sm_small.create("ap-1", risk_level=RiskLevel.CRITICAL)
        sm_small.transition_to_pending(record)
        sm_small.resolve(record, decision_raw=None)
        sm_small.retry(record)
        sm_small.transition_to_pending(record)
        sm_small.resolve(record, decision_raw=None)
        assert record.state == ApprovalState.TERMINAL_BLOCK

    def test_cannot_retry_beyond_budget(self, sm):
        sm_small = ApprovalStateMachine(max_retry_budget=1)
        record = sm_small.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm_small.transition_to_pending(record)
        sm_small.resolve(record, decision_raw=None)
        sm_small.retry(record)
        # Second retry should fail
        with pytest.raises(ValueError, match="budget"):
            sm_small.retry(record)


# ===========================================================================
# Terminal State Guard
# ===========================================================================

class TestTerminalGuard:
    def test_cannot_transition_from_terminal_allow(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.LOW)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw="allow-once")
        with pytest.raises(ValueError, match="terminal"):
            sm.resolve(record, decision_raw="deny")

    def test_cannot_transition_from_terminal_block(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw="deny")
        with pytest.raises(ValueError, match="terminal"):
            sm.retry(record)


# ===========================================================================
# Record Fields
# ===========================================================================

class TestRecordFields:
    def test_record_has_required_fields(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.HIGH)
        assert record.approval_id == "ap-1"
        assert record.risk_level == RiskLevel.HIGH
        assert record.requested_at is not None
        assert record.final is False

    def test_terminal_sets_final(self, sm):
        record = sm.create("ap-1", risk_level=RiskLevel.LOW)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw="allow-once")
        assert record.final is True
        assert record.resolved_at is not None


# ===========================================================================
# Risk-Stratified Retry Budget (F-1, 02 section 6.3)
# ===========================================================================

class TestRiskStratifiedBudget:
    def test_critical_budget_1_retry(self):
        """CRITICAL events allow only 1 retry before exhaustion."""
        sm = ApprovalStateMachine(risk_budgets=RETRY_BUDGET_BY_RISK)
        record = sm.create("ap-1", risk_level=RiskLevel.CRITICAL)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)  # timeout → deferred
        assert record.state == ApprovalState.DEFERRED
        sm.retry(record)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)  # budget exhausted → terminal_block
        assert record.state == ApprovalState.TERMINAL_BLOCK

    def test_low_budget_3_retries(self):
        """LOW events allow 3 retries before exhaustion."""
        sm = ApprovalStateMachine(risk_budgets=RETRY_BUDGET_BY_RISK)
        record = sm.create("ap-1", risk_level=RiskLevel.LOW)
        for i in range(3):
            sm.transition_to_pending(record)
            sm.resolve(record, decision_raw=None)
            assert record.state == ApprovalState.DEFERRED
            sm.retry(record)
        # After 3 retries, next timeout exhausts budget → terminal_defer
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)
        assert record.state == ApprovalState.TERMINAL_DEFER

    def test_medium_backoff_sequence(self):
        """MEDIUM events have backoff [200, 400]."""
        sm = ApprovalStateMachine(risk_budgets=RETRY_BUDGET_BY_RISK)
        record = sm.create("ap-1", risk_level=RiskLevel.MEDIUM)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)
        backoff1 = sm.retry(record)
        assert backoff1 == 200
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)
        backoff2 = sm.retry(record)
        assert backoff2 == 400

    def test_high_no_route_immediate_block(self):
        """HIGH no_route → immediate block (not affected by retry budget)."""
        sm = ApprovalStateMachine(risk_budgets=RETRY_BUDGET_BY_RISK)
        record = sm.create("ap-1", risk_level=RiskLevel.HIGH)
        sm.transition_to_pending(record)
        sm.no_route(record)
        assert record.state == ApprovalState.TERMINAL_BLOCK

    def test_low_no_route_deferred(self):
        """LOW no_route → deferred."""
        sm = ApprovalStateMachine(risk_budgets=RETRY_BUDGET_BY_RISK)
        record = sm.create("ap-1", risk_level=RiskLevel.LOW)
        sm.transition_to_pending(record)
        sm.no_route(record)
        assert record.state == ApprovalState.DEFERRED

    def test_custom_budget_override(self):
        """Custom risk_budgets override defaults."""
        custom = {
            RiskLevel.LOW: RetryBudget(max_retries=1, backoff_ms=[100], max_defer_window_ms=500),
        }
        sm = ApprovalStateMachine(risk_budgets=custom)
        record = sm.create("ap-1", risk_level=RiskLevel.LOW)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)
        sm.retry(record)
        sm.transition_to_pending(record)
        sm.resolve(record, decision_raw=None)
        # Custom budget allows only 1 retry for LOW
        assert record.state == ApprovalState.TERMINAL_DEFER
