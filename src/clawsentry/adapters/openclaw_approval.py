"""
OpenClaw Approval State Machine.

Design basis:
  - 07-openclaw-field-level-mapping.md section 6.1-6.3
  - 03-openclaw-adapter-design.md section 3.3 / 6.2
  - 02-unified-ahp-contract.md section 6.3 (retry budget)
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Optional

from ..gateway.models import (
    DecisionVerdict,
    FailureClass,
    RiskLevel,
    utc_now_iso,
)

logger = logging.getLogger("openclaw-approval")


@dataclass(frozen=True)
class RetryBudget:
    """Risk-stratified retry budget per 02 section 6.3."""
    max_retries: int
    backoff_ms: list[int]
    max_defer_window_ms: int


RETRY_BUDGET_BY_RISK: dict[RiskLevel, RetryBudget] = {
    RiskLevel.CRITICAL: RetryBudget(max_retries=1, backoff_ms=[150], max_defer_window_ms=400),
    RiskLevel.HIGH:     RetryBudget(max_retries=1, backoff_ms=[150], max_defer_window_ms=400),
    RiskLevel.MEDIUM:   RetryBudget(max_retries=2, backoff_ms=[200, 400], max_defer_window_ms=1500),
    RiskLevel.LOW:      RetryBudget(max_retries=3, backoff_ms=[250, 500, 1000], max_defer_window_ms=4000),
}


class ApprovalState(str, enum.Enum):
    REQUESTED = "requested"
    PENDING = "pending"
    DEFERRED = "deferred"
    TERMINAL_ALLOW = "terminal_allow"
    TERMINAL_BLOCK = "terminal_block"
    TERMINAL_DEFER = "terminal_defer"


_TERMINAL_STATES = frozenset({
    ApprovalState.TERMINAL_ALLOW,
    ApprovalState.TERMINAL_BLOCK,
    ApprovalState.TERMINAL_DEFER,
})

# Decision mapping per 07 section 5
_DECISION_MAP: dict[str, DecisionVerdict] = {
    "allow-once": DecisionVerdict.ALLOW,
    "allow-always": DecisionVerdict.ALLOW,
    "deny": DecisionVerdict.BLOCK,
}


@dataclass
class ApprovalRecord:
    """Minimal state machine record per 07 section 6.3."""
    approval_id: str
    risk_level: RiskLevel
    state: ApprovalState = ApprovalState.REQUESTED
    requested_at: str = field(default_factory=utc_now_iso)
    resolved_at: Optional[str] = None
    decision_raw: Optional[str] = None
    decision_mapped: Optional[DecisionVerdict] = None
    failure_class: FailureClass = FailureClass.NONE
    retry_budget_used: int = 0
    final: bool = False


class ApprovalStateMachine:
    """
    Approval state machine per 07 section 6.1.

    Transitions: requested → pending → terminal_allow/terminal_block/deferred
                 deferred → pending (retry) or terminal_block/terminal_defer (budget exhausted)
    """

    def __init__(
        self,
        max_retry_budget: int = 3,
        risk_budgets: dict[RiskLevel, RetryBudget] | None = None,
    ) -> None:
        self.max_retry_budget = max_retry_budget
        self._risk_budgets = risk_budgets  # None = use max_retry_budget flat
        self._records: dict[str, ApprovalRecord] = {}

    def create(self, approval_id: str, risk_level: RiskLevel) -> ApprovalRecord:
        """Create a new approval record in REQUESTED state."""
        record = ApprovalRecord(approval_id=approval_id, risk_level=risk_level)
        self._records[approval_id] = record
        return record

    def get(self, approval_id: str) -> Optional[ApprovalRecord]:
        return self._records.get(approval_id)

    def transition_to_pending(self, record: ApprovalRecord) -> None:
        """Move from REQUESTED or DEFERRED to PENDING."""
        self._check_not_terminal(record)
        if record.state not in (ApprovalState.REQUESTED, ApprovalState.DEFERRED):
            raise ValueError(
                f"Cannot transition to pending from {record.state.value}"
            )
        record.state = ApprovalState.PENDING

    def resolve(self, record: ApprovalRecord, decision_raw: Optional[str]) -> None:
        """
        Resolve a pending approval with a decision.

        decision_raw: "allow-once" | "allow-always" | "deny" | None (timeout)
        """
        self._check_not_terminal(record)
        if record.state != ApprovalState.PENDING:
            raise ValueError(
                f"Cannot resolve from state {record.state.value}, expected pending"
            )

        record.decision_raw = decision_raw

        if decision_raw in _DECISION_MAP:
            # Explicit decision
            record.decision_mapped = _DECISION_MAP[decision_raw]
            record.failure_class = FailureClass.NONE
            record.resolved_at = utc_now_iso()
            record.final = True
            if record.decision_mapped == DecisionVerdict.ALLOW:
                record.state = ApprovalState.TERMINAL_ALLOW
            else:
                record.state = ApprovalState.TERMINAL_BLOCK
        else:
            # decision=null → timeout
            record.failure_class = FailureClass.APPROVAL_TIMEOUT
            budget = self._risk_budgets.get(record.risk_level) if self._risk_budgets else None
            max_retries = budget.max_retries if budget else self.max_retry_budget
            if record.retry_budget_used >= max_retries:
                self._exhaust_budget(record)
            else:
                record.state = ApprovalState.DEFERRED

    def no_route(self, record: ApprovalRecord) -> None:
        """Handle no approval route available."""
        self._check_not_terminal(record)
        record.failure_class = FailureClass.APPROVAL_NO_ROUTE

        if record.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            record.state = ApprovalState.TERMINAL_BLOCK
            record.decision_mapped = DecisionVerdict.BLOCK
            record.resolved_at = utc_now_iso()
            record.final = True
        else:
            record.state = ApprovalState.DEFERRED

    def retry(self, record: ApprovalRecord) -> int:
        """Attempt a retry from DEFERRED state. Returns backoff_ms for this retry."""
        self._check_not_terminal(record)
        if record.state != ApprovalState.DEFERRED:
            raise ValueError(
                f"Cannot retry from state {record.state.value}, expected deferred"
            )
        budget = self._risk_budgets.get(record.risk_level) if self._risk_budgets else None
        max_retries = budget.max_retries if budget else self.max_retry_budget
        if record.retry_budget_used >= max_retries:
            raise ValueError(
                f"Retry budget exhausted ({record.retry_budget_used}/{max_retries})"
            )
        backoff_ms = 0
        if budget and record.retry_budget_used < len(budget.backoff_ms):
            backoff_ms = budget.backoff_ms[record.retry_budget_used]
        record.retry_budget_used += 1
        return backoff_ms

    def _exhaust_budget(self, record: ApprovalRecord) -> None:
        """Handle budget exhaustion based on risk level."""
        record.resolved_at = utc_now_iso()
        record.final = True
        if record.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            record.state = ApprovalState.TERMINAL_BLOCK
            record.decision_mapped = DecisionVerdict.BLOCK
        else:
            record.state = ApprovalState.TERMINAL_DEFER
            record.decision_mapped = DecisionVerdict.DEFER

    @staticmethod
    def _check_not_terminal(record: ApprovalRecord) -> None:
        if record.state in _TERMINAL_STATES:
            raise ValueError(
                f"Cannot transition from terminal state {record.state.value}"
            )
