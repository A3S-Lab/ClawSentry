"""Deterministic L3 trigger policy for Phase 5.2."""

from __future__ import annotations

import json
from typing import Any

from .models import CanonicalEvent, DecisionContext, RiskLevel, RiskSnapshot


_RISK_LEVEL_SCORE = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

_HIGH_RISK_TOOLS = frozenset({
    "bash", "shell", "exec", "sudo", "chmod", "chown", "write", "edit",
    "write_file", "edit_file", "create_file",
})

_MANUAL_FLAGS = ("l3_escalate", "force_l3", "manual_l3_escalation")
_CUMULATIVE_THRESHOLD = 5
_COMPLEX_PAYLOAD_LENGTH = 512
_COMPLEX_PAYLOAD_DEPTH = 3
_COMPLEX_PAYLOAD_KEYS = 6


class L3TriggerPolicy:
    """Decide when to escalate from L2 to L3 deep review."""

    def should_trigger(
        self,
        event: CanonicalEvent,
        context: DecisionContext | None,
        l1_snapshot: RiskSnapshot,
        session_risk_history: list[Any],
    ) -> bool:
        if self._has_manual_flag(context):
            return True
        if self._cumulative_risk_score(session_risk_history, l1_snapshot) >= _CUMULATIVE_THRESHOLD:
            return True
        if self._is_high_risk_tool(event) and self._payload_complexity(event.payload or {}):
            return True
        return False

    def _has_manual_flag(self, context: DecisionContext | None) -> bool:
        if context is None or not isinstance(context.session_risk_summary, dict):
            return False
        return any(bool(context.session_risk_summary.get(flag)) for flag in _MANUAL_FLAGS)

    def _cumulative_risk_score(self, history: list[Any], current: RiskSnapshot) -> int:
        total = 0
        for item in history:
            level = self._extract_risk_level(item)
            total += _RISK_LEVEL_SCORE.get(level, 0)
        total += _RISK_LEVEL_SCORE.get(current.risk_level, 0)
        return total

    def _extract_risk_level(self, item: Any) -> Any:
        if isinstance(item, RiskSnapshot):
            return item.risk_level
        if isinstance(item, dict):
            if "risk_level" in item:
                return str(item.get("risk_level") or "").lower()
            decision = item.get("decision", {})
            if isinstance(decision, dict):
                return str(decision.get("risk_level") or "").lower()
        return None

    def _is_high_risk_tool(self, event: CanonicalEvent) -> bool:
        return str(event.tool_name or "").lower() in _HIGH_RISK_TOOLS

    def _payload_complexity(self, payload: Any) -> bool:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(serialized) >= _COMPLEX_PAYLOAD_LENGTH:
            return True
        if self._max_depth(payload) >= _COMPLEX_PAYLOAD_DEPTH:
            return True
        if isinstance(payload, dict) and len(payload) >= _COMPLEX_PAYLOAD_KEYS:
            return True
        return False

    def _max_depth(self, value: Any, depth: int = 1) -> int:
        if isinstance(value, dict) and value:
            return max(self._max_depth(v, depth + 1) for v in value.values())
        if isinstance(value, list) and value:
            return max(self._max_depth(v, depth + 1) for v in value)
        return depth
